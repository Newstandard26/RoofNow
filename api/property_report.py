"""Vercel Python serverless function: POST /api/property_report.

Phase 2 — builds the homeowner Property Intelligence Report for an address
(reuses the measurement + quote engines via build_property_report). The primary
consumer flow gets its report from POST /api/lead; this standalone endpoint
serves the report directly (e.g. re-fetch / share) per the Phase 2 spec.

Body (JSON): { address, lat?, lng?, lead? }
Also accepts GET ?address=&lat=&lng= for convenience.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the repo-root `roofwall` package importable from /api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.property_report import build_property_report  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402

_RATE_LIMIT_PER_MIN = int(os.environ.get("RATELIMIT_PER_MIN", "30"))
_LIMITER = FixedWindowRateLimiter(max_requests=_RATE_LIMIT_PER_MIN, window_seconds=60.0)


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
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

    def do_OPTIONS(self):  # noqa: N802 - CORS preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _rate_limited(self):
        rl = _LIMITER.check(_client_ip(self.headers))
        if not rl.allowed:
            retry = int(rl.retry_after) + 1
            self._send(429, {"error": "Rate limit exceeded. Try again shortly.",
                             "retry_after_seconds": retry}, {"Retry-After": retry})
            return True
        return False

    def _respond(self, address, lat, lng, lead=None):
        try:
            report = build_property_report(address, lat=lat, lng=lng, lead=lead)
            self._send(200, report, {"Cache-Control": "public, max-age=60"})
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})

    def do_GET(self):  # noqa: N802
        if self._rate_limited():
            return
        params = parse_qs(urlparse(self.path).query)
        address = (params.get("address") or [None])[0]
        lat = _to_float((params.get("lat") or [None])[0])
        lng = _to_float((params.get("lng") or [None])[0])
        self._respond(address, lat, lng)

    def do_POST(self):  # noqa: N802
        if self._rate_limited():
            return
        try:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
        except Exception:  # noqa: BLE001
            self._send(400, {"error": "Invalid JSON body."})
            return
        self._respond(payload.get("address"), _to_float(payload.get("lat")),
                      _to_float(payload.get("lng")), payload.get("lead"))
