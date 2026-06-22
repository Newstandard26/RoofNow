"""Vercel Python serverless function: GET /api/recover.

Progressive enhancement for /api/measure. Runs the real DSM->polygons
recovery (numpy + tifffile + contourpy) and returns the true per-facet roof
diagram plus the Length Diagram (ridge/hip/valley/eave/rake). The frontend
calls this *after* the fast report renders and swaps in the real geometry.

Query: ?lat=..&lng=..  (or ?address=.. which is geocoded server-side).
Returns: {roof_diagram, line_lengths, recovery_status}. Never the API key.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.app import recover_geometry  # noqa: E402


def _first(values):
    try:
        return values[0]
    except (TypeError, IndexError):
        return None


def _first_float(values):
    try:
        return float(values[0])
    except (TypeError, ValueError, IndexError):
        return None


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        # Short cache + revalidate so a geometry change propagates within a
        # minute instead of lingering up to 5 min; serve-stale-while-revalidate
        # keeps it fast. (The frontend also version-tags the URL.)
        self.send_header(
            "Cache-Control",
            "public, max-age=60, stale-while-revalidate=300, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        params = parse_qs(urlparse(self.path).query)
        address = _first(params.get("address"))
        lat = _first_float(params.get("lat"))
        lng = _first_float(params.get("lng"))

        key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if not key:
            self._send(200, {"roof_diagram": None, "line_lengths": None,
                             "recovery_status": "no_api_key"})
            return

        if lat is None or lng is None:
            if not address:
                self._send(400, {"error": "lat/lng or address required"})
                return
            try:
                from roofwall.sources.geocode import Geocoder

                geo = Geocoder(api_key=key).geocode(address)
                lat, lng = geo.lat, geo.lng
            except Exception as exc:  # noqa: BLE001
                self._send(200, {"roof_diagram": None, "line_lengths": None,
                                 "recovery_status": f"geocode_failed: {exc}"})
                return

        result = recover_geometry(lat, lng, key=key)
        self._send(200, result)
