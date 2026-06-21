"""Application service: address -> full roof + wall report dict.

This is the single entry point the web API (and anything else) calls. It
chooses the data path automatically:

  * GOOGLE_MAPS_API_KEY set  -> live Google Solar lookup.
  * otherwise                -> deterministic demo data, so the product is
                                fully usable with no key.

If a live lookup fails for any reason, it degrades to demo data with a note
rather than erroring — the UI always gets a renderable report.
"""

from __future__ import annotations

import math
import os
from typing import Any, Optional

from roofwall.report.render import report_to_dict
from roofwall.sources.demo import demo_full_report
from roofwall.walls.height import elevation_breakdown


def _label(address: Optional[str], lat: Optional[float], lng: Optional[float]) -> str:
    if address:
        return address
    if lat is not None and lng is not None:
        return f"{lat:.5f}, {lng:.5f}"
    return "demo property"


def measure_address(
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    *,
    waste_pct: Optional[float] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Return a full report dict for an address or coordinate."""
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    label = _label(address, lat, lng)

    if key:
        try:
            return _live_report(address, lat, lng, waste_pct=waste_pct, key=key)
        except Exception as exc:  # noqa: BLE001 - always degrade gracefully
            result = demo_full_report(label, waste_pct=waste_pct)
            result["note"] = f"Live lookup unavailable ({exc}); showing demo data."
            return result

    return demo_full_report(label, waste_pct=waste_pct)


def _live_report(
    address: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
    *,
    waste_pct: Optional[float],
    key: str,
    client: Any = None,
    geocoder: Any = None,
) -> dict[str, Any]:
    """Roof from Google Solar; walls estimated from the roof footprint."""
    from roofwall.sources.geocode import Geocoder
    from roofwall.sources.solar import (
        SolarClient,
        imagery_date_iso,
        imagery_quality,
        parse_building_insights,
    )

    if client is None:
        client = SolarClient(api_key=key)
    if geocoder is None:
        geocoder = Geocoder(api_key=key)

    formatted = address
    if lat is None or lng is None:
        if not address:
            raise ValueError("address or lat/lng required")
        geo = geocoder.geocode(address)
        lat, lng, formatted = geo.lat, geo.lng, geo.formatted_address

    # Raw payload so we can read imagery metadata, then parse to a report.
    payload = client.building_insights(lat, lng)
    report = parse_building_insights(payload, waste_pct=waste_pct)
    roof_dict = report_to_dict(report)

    # Walls aren't in the Solar response — estimate from the total roof
    # footprint as a square at a default eave height. Flagged approximate.
    footprint = report.total_footprint_sqft
    side = math.sqrt(footprint) if footprint > 0 else 0.0
    eave_height = 10.0
    ring = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    bd = elevation_breakdown(ring, eave_height)
    walls = {
        "eave_height_ft": eave_height,
        "footprint_ft": {"length": round(side, 1), "width": round(side, 1)},
        "by_direction_sqft": {k: round(v) for k, v in bd.by_direction.items()},
        "gable_area_sqft": 0,
        "gross_wall_area_sqft": round(bd.gross_wall_area),
        "openings_sqft": 0,
        "net_siding_area_sqft": round(bd.gross_wall_area),
        "approximate": True,
        "openings": [],
    }

    return {
        "mode": "live",
        "data_source": "Google Solar",
        "imagery_date": imagery_date_iso(payload),
        "imagery_quality": imagery_quality(payload),
        "address": formatted or address,
        "lat": lat,
        "lng": lng,
        "archetype": None,
        "roof": roof_dict["roof"],
        "facets": roof_dict["facets"],
        "walls": walls,
        # Solar segments carry no facet polygons, so no Length Diagram yet —
        # it comes from the LiDAR/3D path that produces 3D facet outlines.
        "line_lengths": None,
    }
