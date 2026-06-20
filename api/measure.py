"""Vercel Python serverless function: GET /api/measure.

Query params:
  address=<str>           geocode + measure (live mode), or seed (demo mode)
  lat=<float>&lng=<float> skip geocoding
  waste=<float>           override waste fraction, e.g. 0.10

Returns the full roof + wall report as JSON. Runs the real roofwall engine;
falls back to deterministic demo data when GOOGLE_MAPS_API_KEY is unset.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the repo-root `roofwall` package importable from /api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.app import measure_address  # noqa: E402


def _first_float(values):
    try:
        return float(values[0])
    except (TypeError, ValueError, IndexError):
        return None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - Vercel/BaseHTTPRequestHandler API
        params = parse_qs(urlparse(self.path).query)
        address = (params.get("address") or [None])[0]
        lat = _first_float(params.get("lat"))
        lng = _first_float(params.get("lng"))
        waste = _first_float(params.get("waste"))

        try:
            result = measure_address(
                address=address, lat=lat, lng=lng, waste_pct=waste
            )
            status = 200
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
            status = 400

        body = json.dumps(result).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.wfile.write(body)
