"""Vercel Python serverless function: GET /api/measure.

Query params:
  address=<str>           geocode + measure (live mode), or seed (demo mode)
  lat=<float>&lng=<float> skip geocoding
  waste=<float>           override waste fraction, e.g. 0.10

Returns the full roof + wall report as JSON. Runs the real roofwall engine;
falls back to deterministic demo data when GOOGLE_MAPS_API_KEY is unset.

Rate limiting: each client IP is capped at RATELIMIT_PER_MIN requests/minute
(default 30; set to 0 to disable). Live mode hits Google's paid APIs, so the
cap protects against cost/abuse. See roofwall.ratelimit for the trade-offs of
in-process limiting on serverless.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the repo-root `roofwall` package importable from /api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.app import measure_address  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402

# Module-level singleton: persists across invocations on a warm instance.
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
        waste = _first_float(params.get("waste"))

        try:
            result = measure_address(
                address=address, lat=lat, lng=lng, waste_pct=waste
            )
            self._send(200, result, {**rl_headers, "Cache-Control": "public, max-age=60"})
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)}, rl_headers)
