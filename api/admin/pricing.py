"""GET/POST /api/admin/pricing — read + update the active pricing config.

Auth: Authorization: Bearer <token> from /api/admin/login.

GET  -> the active config (normalized dict) for the form to edit.
POST -> { config, preview? }
        preview=true  : validate + return a sample quote, do NOT save.
        otherwise     : validate + save a new active version to Supabase, and
                        return a sample quote computed from it.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# repo root is two levels up from api/admin/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

from roofwall.admin_auth import bearer_token, verify_token  # noqa: E402
from roofwall.quote import build_quote  # noqa: E402
from roofwall.quote import pricing_store  # noqa: E402
from roofwall.quote.pricing import config_from_dict, config_to_dict, load_pricing  # noqa: E402

# A representative roof so the admin sees the effect of a change immediately.
_SAMPLE_REPORT = {
    "mode": "live", "address": "Sample Home, Rockford, IL", "imagery_quality": "MEDIUM",
    "roof": {"total_squares": 25.0, "predominant_pitch": "6/12",
             "structure_complexity": "Normal", "facet_count": 8, "min_confidence": 0.9},
}


def _sample_quote(config):
    q = build_quote(_SAMPLE_REPORT, config=config)
    return {
        "price_range": q.get("price_range"),
        "estimates": [{"name": e["name"], "price_display": e["price_display"],
                       "price": e["price"], "price_per_square": e["price_per_square"]}
                      for e in q.get("estimates", [])],
        "financing": q.get("financing"),
        "roof": {"squares": 25, "pitch": "6/12", "complexity": "Normal"},
    }


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _authed(self) -> bool:
        if not verify_token(bearer_token(self.headers)):
            self._send(401, {"error": "Unauthorized."})
            return False
        return True

    def do_GET(self):  # noqa: N802
        if not self._authed():
            return
        # Normalize through config_to_dict so every field (incl. Phase 3 ones) is present.
        cfg = config_to_dict(load_pricing())
        self._send(200, {"config": cfg, "storage": "supabase" if pricing_store.enabled() else "fallback",
                         "sample": _sample_quote(load_pricing())})

    def do_POST(self):  # noqa: N802
        if not self._authed():
            return
        try:
            length = int(self.headers.get("content-length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            config_in = payload.get("config")
            if not isinstance(config_in, dict):
                raise ValueError("missing 'config' object")
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": f"Invalid request: {exc}"})
            return

        # Validate by building a PricingConfig (raises on bad input).
        try:
            config = config_from_dict(config_in)
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": f"Invalid pricing config: {exc}"})
            return

        normalized = config_to_dict(config)
        sample = _sample_quote(config)

        if payload.get("preview"):
            self._send(200, {"ok": True, "preview": True, "config": normalized, "sample": sample})
            return

        try:
            saved = pricing_store.save_config_dict(normalized, updated_by="admin")
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": f"Could not save: {exc}"})
            return
        self._send(200, {"ok": True, "saved_id": saved.get("id"), "config": normalized,
                         "sample": sample})
