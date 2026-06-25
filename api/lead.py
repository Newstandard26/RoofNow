"""Vercel Python serverless function: POST /api/lead.

RoofNow lead capture. Accepts a JSON body from the instant-quote flow,
validates it (:func:`roofwall.quote.lead.validate_lead`), and records the lead.

Storage in Phase 1 is pluggable and best-effort:
  * always logged to stdout (shows up in Vercel function logs)
  * forwarded to ``LEAD_WEBHOOK_URL`` (e.g. a CRM / Zapier / Slack hook) if set

A failed forward never fails the request — we don't want to lose the homeowner
because a downstream hook is down. Wire a database here when one exists.

Body (JSON): { name, email?, phone?, address, tier?, estimate_low?, estimate_high? }
Requires name + address + (email or phone).
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Make the repo-root `roofwall` package importable from /api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.quote.lead import validate_lead  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402

_RATE_LIMIT_PER_MIN = int(os.environ.get("LEAD_RATELIMIT_PER_MIN", "10"))
_LIMITER = FixedWindowRateLimiter(max_requests=_RATE_LIMIT_PER_MIN, window_seconds=60.0)


def _client_ip(headers) -> str:
    fwd = headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("x-real-ip", "") or "unknown"


def _forward(lead: dict) -> None:
    """Best-effort POST to a configured CRM/webhook. Never raises."""
    url = os.environ.get("LEAD_WEBHOOK_URL")
    if not url:
        return
    try:
        import requests

        requests.post(url, json=lead, timeout=5)
    except Exception as exc:  # noqa: BLE001
        print(f"[lead] webhook forward failed: {exc}", file=sys.stderr)


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
            self._send(
                429,
                {"error": "Too many submissions. Try again shortly.",
                 "retry_after_seconds": retry},
                {"Retry-After": retry},
            )
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

        lead, errors = validate_lead(payload)
        if errors:
            self._send(400, {"error": "Validation failed.", "errors": errors})
            return

        # Record: stdout log (always) + optional webhook forward.
        print(f"[lead] {json.dumps(lead)}")
        _forward(lead)

        self._send(200, {
            "ok": True,
            "message": "Thanks! New Standard Restoration will reach out to "
                       "schedule your free inspection.",
        })
