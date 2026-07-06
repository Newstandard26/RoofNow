"""Google Street View Static image — the home photo on the proposal cover.

Best-effort: returns JPEG bytes for an address/lat-lng, or ``None`` (no key, no
imagery, or any error) so the proposal falls back to a branded gradient cover.
Uses the existing ``GOOGLE_MAPS_API_KEY``.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

_META = "https://maps.googleapis.com/maps/api/streetview/metadata"
_IMG = "https://maps.googleapis.com/maps/api/streetview"


def street_view_image(
    address: Optional[str] = None,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    api_key: Optional[str] = None,
    size: str = "640x400",
    http_get=None,
) -> Optional[bytes]:
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    location = f"{lat},{lng}" if (lat is not None and lng is not None) else address
    if not key or not location:
        return None
    get = http_get or _default_get
    try:
        # Confirm imagery exists before spending an image request.
        meta_status, meta = get(_META, {"location": location, "key": key}, expect_json=True)
        if meta_status != 200 or not isinstance(meta, dict) or meta.get("status") != "OK":
            return None
        img_status, body = get(
            _IMG,
            {"location": location, "size": size, "fov": "78", "pitch": "8",
             "source": "outdoor", "key": key},
            expect_json=False,
        )
        if img_status == 200 and isinstance(body, (bytes, bytearray)) and len(body) > 1500:
            return bytes(body)
    except Exception as exc:  # noqa: BLE001
        print(f"[streetview] failed: {exc}", file=sys.stderr)
    return None


def _default_get(url, params, *, expect_json):
    import requests

    r = requests.get(url, params=params, timeout=8)
    if expect_json:
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, None
    return r.status_code, r.content
