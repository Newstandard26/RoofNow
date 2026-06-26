"""POST /api/admin/login — exchange the admin password for a short-lived token."""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# repo root is two levels up from api/admin/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

from roofwall.admin_auth import admin_enabled, check_password, issue_token  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402

_LIMITER = FixedWindowRateLimiter(max_requests=10, window_seconds=60.0)


def _client_ip(headers) -> str:
    fwd = headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("x-real-ip", "") or "unknown"


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        if not _LIMITER.check(_client_ip(self.headers)).allowed:
            self._send(429, {"error": "Too many attempts. Try again shortly."})
            return
        if not admin_enabled():
            self._send(503, {"error": "Admin is not configured."})
            return
        try:
            length = int(self.headers.get("content-length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            self._send(400, {"error": "Invalid JSON body."})
            return

        if check_password(payload.get("password", "")):
            self._send(200, {"ok": True, "token": issue_token()})
        else:
            self._send(401, {"error": "Incorrect password."})
