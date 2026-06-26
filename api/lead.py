"""Vercel Python serverless function: POST /api/lead.

RoofNow's gated intake + instant quote. The intake form is required to see a
quote, so this single endpoint:

  1. validates the lead (first name, last name, address, phone, email)
  2. measures the roof + builds the instant quote (reuses the measurement engine)
  3. funnels the lead to the sales channels (email / Slack / Zapier webhook)
  4. returns the quote to the browser

The lead is funneled even if measurement fails, so a noisy address never costs
a lead. Funneling is best-effort and never blocks the response.

Body (JSON): { first_name, last_name, address, phone, email, tier? }
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Make the repo-root `roofwall` package importable from /api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.property_report import build_property_report  # noqa: E402
from roofwall.quote.funnel import funnel_lead  # noqa: E402
from roofwall.quote.lead import validate_lead  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402

_RATE_LIMIT_PER_MIN = int(os.environ.get("LEAD_RATELIMIT_PER_MIN", "10"))
_LIMITER = FixedWindowRateLimiter(max_requests=_RATE_LIMIT_PER_MIN, window_seconds=60.0)


def _client_ip(headers) -> str:
    fwd = headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("x-real-ip", "") or "unknown"


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _funnel_quote(report):
    """A small quote-shaped dict for the lead funnel (price range + confidence)."""
    if not report:
        return None
    q = report.get("quote") or {}
    return {"price_range": q.get("price_range"), "confidence": report.get("confidence")}


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

        # Build the full Property Intelligence Report (reuses measurement + quote
        # in one pass) so the browser gets the report and the funnel carries the
        # estimate. Prefer the exact lat/lng from address autocomplete.
        report = build_property_report(
            lead["address"],
            lat=_to_float(payload.get("lat")),
            lng=_to_float(payload.get("lng")),
            lead=lead,
        )
        fq = _funnel_quote(report)
        if fq and fq.get("price_range") and not lead.get("estimate_low"):
            lead["estimate_low"] = fq["price_range"].get("low")
            lead["estimate_high"] = fq["price_range"].get("high")

        print(f"[lead] {json.dumps(lead)}")
        funnel_lead(lead, fq)

        self._send(200, {
            "ok": True,
            "message": "Thanks! New Standard Restoration will reach out to "
                       "schedule your free inspection.",
            "report": report,
        })
