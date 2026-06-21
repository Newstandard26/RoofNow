"""Vercel Python serverless function: GET /api/facets.

Returns a BuildingModel (per-facet 3D polygons) plus its snapped Length
Diagram. M1 plumbing: proves BuildingModel -> snapping -> edge classifier ->
line lengths end to end. Query: ?address=... or ?lat=..&lng=.. (optional).
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from roofwall.sources.facets import building_model_for  # noqa: E402


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
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        params = parse_qs(urlparse(self.path).query)
        address = _first(params.get("address"))
        lat = _first_float(params.get("lat"))
        lng = _first_float(params.get("lng"))

        try:
            model = building_model_for(address=address, lat=lat, lng=lng)
            payload = {
                "model": model.to_dict(),
                "line_lengths": model.line_lengths(),
            }
            status = 200
        except Exception as exc:  # noqa: BLE001
            payload = {"error": str(exc)}
            status = 400

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.wfile.write(body)
