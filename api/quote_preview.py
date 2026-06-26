"""Vercel Python serverless function: GET /api/quote_preview.

Step 1 of the RoofNow landing flow: address-only teaser. Confirms we found the
roof and returns a confidence read — but NOT the Good/Better/Best prices, which
stay gated behind the contact form (POST /api/lead).

Query params:
  address=<str>           geocode + measure (live), or seed (demo)
  lat=<float>&lng=<float> skip geocoding

Rate limited like /api/measure (live mode hits Google's paid APIs).
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the repo-root `roofwall` package importable from /api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.app import measure_address  # noqa: E402
from roofwall.quote import build_preview  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402

_RATE_LIMIT_PER_MIN = int(os.environ.get("RATELIMIT_PER_MIN", "30"))
_LIMITER = FixedWindowRateLimiter(max_requests=_RATE_LIMIT_PER_MIN, window_seconds=60.0)


def _first_float(values):
    try:
        return float(values[0])
    except (TypeError, ValueError, IndexError):
        return None


def _client_ip(headers) -> str:
    fwd = headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("x-real-ip", "") or "unknown"


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        rl = _LIMITER.check(_client_ip(self.headers))
        rl_headers = {
            "X-RateLimit-Limit": rl.limit,
            "X-RateLimit-Remaining": rl.remaining,
        }
        if not rl.allowed:
            retry = int(rl.retry_after) + 1
            self._send(
                429,
                {"error": "Rate limit exceeded. Try again shortly.",
                 "retry_after_seconds": retry},
                {**rl_headers, "Retry-After": retry},
            )
            return

        params = parse_qs(urlparse(self.path).query)
        address = (params.get("address") or [None])[0]
        lat = _first_float(params.get("lat"))
        lng = _first_float(params.get("lng"))

        try:
            report = measure_address(address=address, lat=lat, lng=lng)
            preview = build_preview(report)
            self._send(200, preview, {**rl_headers, "Cache-Control": "public, max-age=60"})
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)}, rl_headers)
