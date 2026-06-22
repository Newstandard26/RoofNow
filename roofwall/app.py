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
import re
import sys
from typing import Any, Optional

from roofwall.report.render import report_to_dict
from roofwall.sources.demo import demo_full_report
from roofwall.sources.geocode import GeocodeError, Geocoder
from roofwall.sources.solar import CoverageError, SolarClient, SolarError
from roofwall.walls.height import elevation_breakdown


def _label(address: Optional[str], lat: Optional[float], lng: Optional[float]) -> str:
    if address:
        return address
    if lat is not None and lng is not None:
        return f"{lat:.5f}, {lng:.5f}"
    return "demo property"


def _log(msg: str) -> None:
    """Write to stderr so it surfaces in Vercel function logs (never the key)."""
    print(f"[api/measure] {msg}", file=sys.stderr)


def _demo(label: str, waste_pct: Optional[float], reason: str) -> dict[str, Any]:
    """Demo report annotated with *why* the live path wasn't used."""
    result = demo_full_report(label, waste_pct=waste_pct)
    result["demo_reason"] = reason
    return result


def measure_address(
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    *,
    waste_pct: Optional[float] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Return a full report dict. On any demo fallback, sets ``demo_reason``.

    demo_reason values: ``no_api_key``, ``geocode_failed: <status+msg>``,
    ``solar_not_covered``, ``solar_error: <status+msg>``, ``exception: <msg>``.
    The key is never included in any message.
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    label = _label(address, lat, lng)

    if not key:
        _log("demo fallback: no_api_key")
        return _demo(label, waste_pct, "no_api_key")

    try:
        return _live_report(address, lat, lng, waste_pct=waste_pct, key=key)
    except GeocodeError as exc:
        reason = f"geocode_failed: {exc}"
    except CoverageError:  # subclass of SolarError — must precede it
        reason = "solar_not_covered"
    except SolarError as exc:
        reason = f"solar_error: {exc}"
    except Exception as exc:  # noqa: BLE001
        reason = f"exception: {exc}"

    _log(f"live fallback to demo: {reason}")
    return _demo(label, waste_pct, reason)


def _solar_http_status(client: "SolarClient", lat: float, lng: float) -> Optional[int]:
    """Raw buildingInsights HTTP status (200/404/4xx) without raising."""
    try:
        client.building_insights(lat, lng)
        return 200
    except CoverageError:
        return 404
    except SolarError as exc:
        m = re.search(r"Solar API (\d+)", str(exc))
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def live_debug(
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    *,
    api_key: Optional[str] = None,
    client: Any = None,
    geocoder: Any = None,
) -> dict[str, Any]:
    """Diagnostics for the live path. Reports hasKey (bool only), the geocoded
    lat/lng, and the raw Solar HTTP status — never the key itself.
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    info: dict[str, Any] = {
        "hasKey": bool(key),
        "address": address,
        "lat": lat,
        "lng": lng,
        "geocode": None,
        "solar_http_status": None,
        "error": None,
    }
    if not key:
        info["error"] = "no_api_key"
        return info

    if client is None:
        client = SolarClient(api_key=key)
    if geocoder is None:
        geocoder = Geocoder(api_key=key)

    if lat is None or lng is None:
        if not address:
            info["error"] = "no_address_or_latlng"
            return info
        try:
            geo = geocoder.geocode(address)
            lat, lng = geo.lat, geo.lng
            info["geocode"] = "ok"
        except GeocodeError as exc:
            info["geocode"] = f"failed: {exc}"
            return info
    info["lat"], info["lng"] = lat, lng
    info["solar_http_status"] = _solar_http_status(client, lat, lng)
    return info


def recover_line_lengths(
    lat: float, lng: float, *, key: str, http_get: Any = None
) -> tuple[Optional[dict[str, Any]], str]:
    """Try DSM->polygons recovery -> (line_lengths | None, recovery_status).

    Never raises. recovery_status values:
      ``ok:<facets>`` | ``deps_missing:<mod>`` | ``no_dsm`` | ``error: <msg>``.
    If ``ROOFWALL_CV_URL`` is set we call that service (the heavy CV stack can't
    run in the Vercel function); otherwise we try in-process (works where the
    geospatial deps + key + network are available).
    """
    url = os.environ.get("ROOFWALL_CV_URL")
    if url:
        return _recover_via_service(url, lat, lng, http_get=http_get)
    return _recover_in_process(lat, lng, key)


def _recover_via_service(
    url: str, lat: float, lng: float, *, http_get: Any = None
) -> tuple[Optional[dict[str, Any]], str]:
    try:
        if http_get is None:
            import requests

            resp = requests.get(
                url.rstrip("/") + "/facets",
                params={"lat": lat, "lng": lng},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
        else:
            data = http_get(url.rstrip("/") + "/facets", {"lat": lat, "lng": lng})
        ll = data.get("line_lengths")
        if ll:
            facets = (data.get("model") or {}).get("facets") or []
            return ll, f"ok:{len(facets)}"
        return None, data.get("recovery_status") or "no_polygons"
    except Exception as exc:  # noqa: BLE001
        return None, f"error: {exc}"


def _recover_in_process(
    lat: float, lng: float, key: str
) -> tuple[Optional[dict[str, Any]], str]:
    # Check the heavy geospatial deps are present BEFORE doing any work. On the
    # Vercel function they're absent, so we must NOT download the DSM only to
    # fail on the missing lib — that wasted a paid dataLayers call + seconds of
    # latency on every live measure. Short-circuit fast and cheap.
    import importlib.util

    for mod in ("numpy", "rasterio", "pyproj", "skimage", "shapely"):
        if importlib.util.find_spec(mod) is None:
            return None, f"deps_missing:{mod}"
    try:
        from roofwall.cv.solar_dsm import build_model_from_solar_dsm

        model = build_model_from_solar_dsm(lat, lng, key)
        return model.line_lengths(), f"ok:{len(model.facets)}"
    except NotImplementedError:
        return None, "no_dsm"
    except Exception as exc:  # noqa: BLE001
        _log(f"recovery error: {exc}")
        return None, f"error: {exc}"


def _geometry_from_model(model) -> dict[str, Any]:
    """Project a recovered BuildingModel to the UI geometry payload."""
    from roofwall.report.diagram import from_edge_facets

    return {
        "roof_diagram": from_edge_facets(model.to_edge_facets()),
        "line_lengths": model.line_lengths(),
        "recovery_status": f"ok:{len(model.facets)}",
    }


def _empty_geometry(status: str) -> dict[str, Any]:
    return {"roof_diagram": None, "line_lengths": None, "recovery_status": status}


def recover_geometry(
    lat: float, lng: float, *, key: str, http_get: Any = None
) -> dict[str, Any]:
    """Full DSM->polygons recovery -> real per-facet roof diagram + Length
    Diagram. Returns ``{roof_diagram, line_lengths, recovery_status}``; never
    raises. Used by ``/api/recover`` for progressive enhancement so the slow,
    heavy recovery runs *after* the fast report renders.

    If ``ROOFWALL_CV_URL`` is set we call that service (highest fidelity, heavy
    CV stack); otherwise we run the lightweight in-process recovery
    (numpy + tifffile + contourpy), which fits a Vercel function.
    """
    url = os.environ.get("ROOFWALL_CV_URL")
    if url:
        return _recover_geometry_via_service(url, lat, lng, http_get=http_get)
    return _recover_geometry_in_process(lat, lng, key)


def _recover_geometry_via_service(
    url: str, lat: float, lng: float, *, http_get: Any = None
) -> dict[str, Any]:
    try:
        if http_get is None:
            import requests

            resp = requests.get(
                url.rstrip("/") + "/facets",
                params={"lat": lat, "lng": lng},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
        else:
            data = http_get(url.rstrip("/") + "/facets", {"lat": lat, "lng": lng})
        model_d = data.get("model") or {}
        facets = model_d.get("facets") or []
        if not facets:
            return _empty_geometry(data.get("recovery_status") or "no_polygons")
        from roofwall.model import BuildingModel, ModelFacet, Origin
        from roofwall.report.diagram import from_edge_facets

        origin = model_d.get("origin") or {}
        model = BuildingModel(
            facets=[ModelFacet(str(f["id"]), [tuple(v) for v in f["verts"]])
                    for f in facets],
            origin=Origin(origin.get("lat", lat), origin.get("lng", lng)),
            source=model_d.get("source", "solar-dsm"),
        )
        return {
            "roof_diagram": from_edge_facets(model.to_edge_facets()),
            "line_lengths": data.get("line_lengths") or model.line_lengths(),
            "recovery_status": f"ok:{len(facets)}",
        }
    except Exception as exc:  # noqa: BLE001
        return _empty_geometry(f"error: {exc}")


def _recover_geometry_in_process(lat: float, lng: float, key: str) -> dict[str, Any]:
    # Lightweight stack only (numpy + tifffile + contourpy). Verify the deps are
    # present before any paid dataLayers download so a misconfigured deploy fails
    # fast and cheap with a clear status instead of mid-recovery.
    import importlib.util

    for mod in ("numpy", "tifffile", "contourpy"):
        if importlib.util.find_spec(mod) is None:
            return _empty_geometry(f"deps_missing:{mod}")
    try:
        from roofwall.cv.light import build_model_light

        model = build_model_light(lat, lng, key)
        if not model.facets:
            return _empty_geometry("no_polygons")
        return _geometry_from_model(model)
    except Exception as exc:  # noqa: BLE001
        _log(f"geometry recovery error: {exc}")
        return _empty_geometry(f"error: {exc}")


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

    # DSM->polygons recovery (ridge/hip/valley/eave/rake). Never raises; on any
    # failure line_lengths stays None and recovery_status explains why, so the
    # report still renders.
    line_lengths, recovery_status = recover_line_lengths(lat, lng, key=key)

    from roofwall.report.diagram import from_solar as _solar_diagram

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
        "line_lengths": line_lengths,
        "recovery_status": recovery_status,
        "roof_diagram": _solar_diagram(payload),
    }
