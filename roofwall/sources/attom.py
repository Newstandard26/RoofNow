"""ATTOM property data — enrich a RoofNow quote with real property facts.

On report generation (NOT on the cheap address preview) we look the property up
in ATTOM and pull the facts that matter for roofing + a sales report: year
built, building size, stories, and roof cover/material where ATTOM has it, plus
owner/AVM when the plan includes them.

Design:
  * Server-side only — the key (``ATTOM_API_KEY``) never reaches the browser.
  * Best-effort: any error / no-match returns ``None`` so the report still
    renders without ATTOM.
  * Endpoint auto-detect: tries expandedprofile -> detail -> basicprofile and
    uses whatever the key is entitled to.
  * ``http_get`` is injectable for tests.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"
_ENDPOINTS = ("property/expandedprofile", "property/detail", "property/basicprofile")

# (status_code, json) tuple
HttpGet = Callable[[str, Dict[str, str], Dict[str, str]], Tuple[int, Any]]


def _requests_get(url: str, headers: Dict[str, str], params: Dict[str, str]) -> Tuple[int, Any]:
    import requests

    r = requests.get(url, headers=headers, params=params, timeout=8)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = None
    return r.status_code, body


def split_address(address: str) -> Optional[Tuple[str, str]]:
    """'4150 N Rockton Ave, Rockford, IL 61101, USA' -> ('4150 N Rockton Ave',
    'Rockford, IL 61101'). ATTOM wants address1 (street) + address2 (city/st/zip)."""
    if not address:
        return None
    parts = [p.strip() for p in str(address).split(",") if p.strip()]
    # drop a trailing country token
    if parts and parts[-1].upper() in ("USA", "US", "UNITED STATES"):
        parts = parts[:-1]
    if len(parts) < 2:
        return None
    return parts[0], ", ".join(parts[1:])


def _ci_get(d: Any, key: str) -> Any:
    """Case-insensitive dict get."""
    if not isinstance(d, dict):
        return None
    if key in d:
        return d[key]
    lk = key.lower()
    for k, v in d.items():
        if str(k).lower() == lk:
            return v
    return None


def _dig(obj: Any, *paths: str) -> Any:
    """Return the first non-empty value among dot-paths, case-insensitively."""
    for path in paths:
        cur = obj
        for seg in path.split("."):
            cur = _ci_get(cur, seg)
            if cur is None:
                break
        if cur not in (None, "", []):
            return cur
    return None


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_property(payload: Any) -> Optional[Dict[str, Any]]:
    """Normalize an ATTOM property response into RoofNow-friendly facts."""
    if not isinstance(payload, dict):
        return None
    props = _ci_get(payload, "property")
    if not isinstance(props, list) or not props:
        return None
    p = props[0]

    building_sqft = _to_int(_dig(p, "building.size.universalsize", "building.size.bldgsize",
                                 "building.size.livingsize", "building.size.grosssize"))
    year_built = _to_int(_dig(p, "summary.yearbuilt", "building.summary.yearbuilteffective",
                              "summary.yearBuilt"))
    stories = _dig(p, "building.summary.levels", "building.summary.storyDesc",
                   "building.summary.story")
    roof_cover = _dig(p, "building.construction.roofcover", "building.construction.roofCover")
    roof_frame = _dig(p, "building.construction.roofframe", "building.construction.roofFrame")
    beds = _to_int(_dig(p, "building.rooms.beds"))
    baths = _dig(p, "building.rooms.bathstotal", "building.rooms.bathsTotal")
    prop_type = _dig(p, "summary.proptype", "summary.propsubtype", "summary.propclass")
    lot_sqft = _to_int(_dig(p, "lot.lotsize2"))  # lotsize2 is sqft; lotsize1 is acres
    attom_id = _dig(p, "identifier.attomId", "identifier.Id", "identifier.attomid")

    owner = None
    o1 = _dig(p, "owner.owner1")
    if isinstance(o1, dict):
        name = " ".join(str(x) for x in (_ci_get(o1, "firstnameandmi") or _ci_get(o1, "firstname"),
                                         _ci_get(o1, "lastname")) if x)
        owner = name.strip() or None

    avm_value = _to_int(_dig(p, "avm.amount.value"))

    facts: Dict[str, Any] = {
        "attom_id": str(attom_id) if attom_id else None,
        "year_built": year_built,
        "building_sqft": building_sqft,
        "stories": str(stories) if stories not in (None, "") else None,
        "roof_cover": str(roof_cover) if roof_cover else None,
        "roof_frame": str(roof_frame) if roof_frame else None,
        "beds": beds,
        "baths": str(baths) if baths not in (None, "") else None,
        "lot_sqft": lot_sqft,
        "property_type": str(prop_type) if prop_type else None,
        "owner": owner,
        "avm_value": avm_value,
        "source": "attom",
    }
    # Only return if we actually learned something useful.
    if any(facts[k] is not None for k in ("year_built", "building_sqft", "roof_cover", "stories")):
        return facts
    return None


def fetch_property_facts(
    address: str,
    *,
    api_key: Optional[str] = None,
    http_get: Optional[HttpGet] = None,
) -> Optional[Dict[str, Any]]:
    """Look an address up in ATTOM and return normalized facts, or ``None``.

    Never raises. Tries the property endpoints in order of richness and uses the
    first one the key is entitled to.
    """
    key = api_key or os.environ.get("ATTOM_API_KEY")
    if not key:
        return None
    split = split_address(address)
    if not split:
        return None
    address1, address2 = split
    get = http_get or _requests_get
    headers = {"Accept": "application/json", "apikey": key}
    params = {"address1": address1, "address2": address2}

    for endpoint in _ENDPOINTS:
        try:
            status, body = get(f"{BASE_URL}/{endpoint}", headers, params)
        except Exception as exc:  # noqa: BLE001
            print(f"[attom] {endpoint} request failed: {exc}", file=sys.stderr)
            continue
        if status == 200:
            facts = parse_property(body)
            if facts:
                facts["endpoint"] = endpoint
                return facts
            # 200 but no usable property -> try a richer/another endpoint
            continue
        if status in (401, 403):
            # not entitled to this endpoint — try the next
            continue
        # 400/404/SuccessWithoutResult etc. — address likely not found; stop early
        if status == 400:
            continue
    return None
