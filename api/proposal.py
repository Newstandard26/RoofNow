"""GET /api/proposal — the branded, mailable roof-proposal PDF.

Auto-available for every lead: /api/lead returns a `proposal_url` pointing here
(also sent to the CRM), and the customer's report shows a Download button.

Query: address, first_name, last_name, name?, email?, phone?, lat?, lng?
Returns application/pdf. Reuses build_property_report (measurement + Good/Better/
Best pricing + ATTOM) and a Street View cover photo.
"""

import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.property_report import build_property_report  # noqa: E402
from roofwall.proposal import build_proposal_pdf  # noqa: E402
from roofwall.ratelimit import FixedWindowRateLimiter  # noqa: E402
from roofwall.sources.streetview import street_view_image  # noqa: E402

_LIMITER = FixedWindowRateLimiter(
    max_requests=int(os.environ.get("RATELIMIT_PER_MIN", "30")), window_seconds=60.0)


def _f(v):
    try:
        return float(v[0])
    except (TypeError, ValueError, IndexError):
        return None


def _s(params, key):
    return (params.get(key) or [None])[0]


def _client_ip(headers) -> str:
    fwd = headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (headers.get("x-real-ip", "") or "unknown")


def _filename(address: str) -> str:
    base = re.sub(r"[^A-Za-z0-9 ]+", "", (address or "Roof").split(",")[0]).strip() or "Roof"
    return f"{base} - Proposal.pdf"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if not _LIMITER.check(_client_ip(self.headers)).allowed:
            self.send_response(429); self.end_headers(); return

        params = parse_qs(urlparse(self.path).query)
        address = _s(params, "address")
        lat, lng = _f(params.get("lat")), _f(params.get("lng"))
        customer = {
            "first_name": _s(params, "first_name"), "last_name": _s(params, "last_name"),
            "name": _s(params, "name"), "email": _s(params, "email"),
            "phone": _s(params, "phone"), "address": address,
        }
        try:
            report = build_property_report(address, lat=lat, lng=lng, lead=customer)
            cover = street_view_image(address, lat=lat, lng=lng)
            pdf = build_proposal_pdf(report, customer, cover_image=cover)
        except Exception as exc:  # noqa: BLE001
            print(f"[proposal] failed: {exc}", file=sys.stderr)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Could not generate proposal."}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{_filename(address)}"')
        self.send_header("Content-Length", str(len(pdf)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(pdf)
