"""Vercel Python serverless function: GET /api/suggest?q=...

Address type-ahead. Proxies Google Geocoding server-side (the key never
reaches the browser) and returns candidate addresses with coordinates so the
client can drop a map marker to verify the structure before ordering.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402
from roofwall.sources.geocode import suggest_addresses  # noqa: E402

# Type-ahead fires often; allow a higher per-IP budget than /measure.
_LIMITER = FixedWindowRateLimiter(
    max_requests=int(os.environ.get("SUGGEST_RATELIMIT_PER_MIN", "120")),
    window_seconds=60.0,
)


def _client_ip(headers) -> str:
    fwd = headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("x-real-ip", "") or "unknown"


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload, extra=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300")
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        rl = _LIMITER.check(_client_ip(self.headers))
        if not rl.allowed:
            self._send(429, {"suggestions": [], "error": "rate_limited"},
                       {"Retry-After": int(rl.retry_after) + 1})
            return
        params = parse_qs(urlparse(self.path).query)
        q = (params.get("q") or params.get("address") or [""])[0]
        try:
            suggestions = suggest_addresses(q)
        except Exception as exc:  # noqa: BLE001
            self._send(200, {"suggestions": [], "error": str(exc)})
            return
        self._send(200, {"suggestions": suggestions})
