"""Vercel Python serverless function: GET /api/config.

Serves the **browser** Google Maps key (Maps JavaScript API + Places API) to
the client so it can render the Google map and Places Autocomplete. This key
is a referrer-restricted, browser-safe key — distinct from the server-side
GOOGLE_MAPS_API_KEY (Solar/Geocoding), which is never exposed.
"""

import json
import os
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        body = json.dumps({
            "maps_browser_key": os.environ.get("GOOGLE_MAPS_BROWSER_KEY", ""),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)
