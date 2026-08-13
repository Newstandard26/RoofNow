"""Vercel Python serverless function: POST /api/select.

Fired when a homeowner clicks "Select the <name> package" on their quote
report. Sends an email update to the team (SMTP sink from the lead funnel) —
deliberately NO CRM/Zapier webhook and no Slack: the CRM lead was already
created at the unlock step and stays untouched.

Body (JSON): { first_name, last_name, email, phone, address,
               package_key, package_name, price_display?, shingle_name?,
               proposal_url? }
Always returns 200 {ok: true} on a valid body — email delivery is
best-effort and never surfaces an error to the customer.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Make the repo-root `roofwall` package importable from /api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.quote.funnel import send_selection_email  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402

_RATE_LIMIT_PER_MIN = int(os.environ.get("SELECT_RATELIMIT_PER_MIN", "12"))
_LIMITER = FixedWindowRateLimiter(max_requests=_RATE_LIMIT_PER_MIN, window_seconds=60.0)

_MAX_FIELD = 300


def _client_ip(headers) -> str:
    fwd = headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("x-real-ip", "") or "unknown"


def _clean(v) -> str:
    return str(v or "").strip()[:_MAX_FIELD]


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
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        rl = _LIMITER.check(_client_ip(self.headers))
        if not rl.allowed:
            retry = int(rl.retry_after) + 1
            self._send(429, {"error": "Too many requests.", "retry_after_seconds": retry},
                       {"Retry-After": retry})
            return

        try:
            length = int(self.headers.get("content-length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
        except Exception:  # noqa: BLE001
            self._send(400, {"error": "Invalid JSON body."})
            return

        selection = {
            "package_key": _clean(payload.get("package_key")),
            "package_name": _clean(payload.get("package_name")),
            "price_display": _clean(payload.get("price_display")),
            "shingle_name": _clean(payload.get("shingle_name")),
        }
        lead = {
            "first_name": _clean(payload.get("first_name")),
            "last_name": _clean(payload.get("last_name")),
            "email": _clean(payload.get("email")),
            "phone": _clean(payload.get("phone")),
            "address": _clean(payload.get("address")),
            "proposal_url": _clean(payload.get("proposal_url")),
        }
        if not selection["package_key"] and not selection["package_name"]:
            self._send(400, {"error": "Missing package."})
            return
        if not (lead["email"] or lead["phone"] or lead["address"]):
            self._send(400, {"error": "Missing lead contact."})
            return

        status = send_selection_email(lead, selection)
        print(f"[select] {lead.get('email') or lead.get('address')} -> "
              f"{selection['package_key'] or selection['package_name']} (email: {status})",
              file=sys.stderr)
        self._send(200, {"ok": True})
