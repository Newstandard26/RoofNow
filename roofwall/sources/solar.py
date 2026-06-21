"""Google Maps Solar API client (Phase 1).

Endpoints used:
  * ``buildingInsights:findClosest`` — roof geometry (pitch/azimuth/area
    per segment). This is the fast path to a working report.
  * ``dataLayers:get`` — signed GeoTIFF URLs (DSM/RGB/mask). URLs expire
    in ~1 hour, so download immediately.

The parsing logic (:func:`parse_building_insights`) is decoupled from HTTP
so it can be unit-tested against a captured JSON payload — no key or
network required. A 404 from ``findClosest`` means no Solar coverage and
raises :class:`CoverageError`, the signal to fall back to the LiDAR path.

Response shape parsed (per spec):
  solarPotential.roofSegmentStats[]:
    pitchDegrees, azimuthDegrees,
    stats.areaMeters2, stats.groundAreaMeters2,
    boundingBox, center, planeHeightAtCenterMeters
  solarPotential.wholeRoofStats.areaMeters2
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from roofwall.measurement.engine import (
    FacetMeasurement,
    Pitch,
    RoofReport,
    sqm_to_sqft,
    suggest_waste_from_facets,
    summarize_roof,
)

SOLAR_BASE_URL = "https://solar.googleapis.com/v1"
DEFAULT_TIMEOUT = 30


class SolarError(RuntimeError):
    """Generic Solar API failure."""


class CoverageError(SolarError):
    """No Solar coverage for this location (HTTP 404) — fall back to LiDAR."""


def _ground_area_m2(segment: dict[str, Any]) -> Optional[float]:
    """Plan/footprint area of a segment in m², if present."""
    stats = segment.get("stats") or {}
    val = stats.get("groundAreaMeters2")
    return float(val) if val is not None else None


def parse_building_insights(
    payload: dict[str, Any],
    *,
    source: str = "solar",
    waste_pct: float | None = None,
) -> RoofReport:
    """Convert a ``buildingInsights`` payload into a :class:`RoofReport`.

    We feed each segment's **ground** (plan) area through the engine's
    ``measure_facet`` so the sloped area is derived consistently from the
    pitch multiplier. Where ground area is missing we fall back to the
    reported (already-sloped) ``areaMeters2`` and infer the plan area.
    """
    solar = payload.get("solarPotential")
    if not solar:
        raise SolarError("payload missing solarPotential")

    segments = solar.get("roofSegmentStats") or []
    if not segments:
        raise SolarError("no roofSegmentStats in payload")

    facets: list[FacetMeasurement] = []
    for seg in segments:
        pitch = Pitch.from_degrees(float(seg.get("pitchDegrees", 0.0)))
        azimuth = float(seg.get("azimuthDegrees", 0.0))

        ground_m2 = _ground_area_m2(seg)
        if ground_m2 is None:
            # Only sloped area given: back it out to a plan area so the
            # engine recomputes consistently.
            sloped_m2 = float((seg.get("stats") or {}).get("areaMeters2", 0.0))
            ground_m2 = sloped_m2 / pitch.multiplier if pitch.multiplier else sloped_m2

        facets.append(
            _facet_from_ground_area(
                ground_area_sqft=sqm_to_sqft(ground_m2),
                pitch=pitch,
                azimuth_deg=azimuth,
                source=source,
            )
        )

    if waste_pct is None:
        waste_pct = suggest_waste_from_facets(len(facets))
    return summarize_roof(facets, waste_pct=waste_pct)


def _facet_from_ground_area(
    *, ground_area_sqft: float, pitch: Pitch, azimuth_deg: float, source: str
) -> FacetMeasurement:
    from roofwall.measurement.engine import measure_facet

    return measure_facet(
        footprint_area_sqft=ground_area_sqft,
        pitch=pitch,
        azimuth_deg=azimuth_deg,
        source=source,
    )


def whole_roof_area_sqft(payload: dict[str, Any]) -> Optional[float]:
    """Solar's own ``wholeRoofStats.areaMeters2`` in sqft, for cross-check."""
    solar = payload.get("solarPotential") or {}
    whole = solar.get("wholeRoofStats") or {}
    area = whole.get("areaMeters2")
    return sqm_to_sqft(float(area)) if area is not None else None


def imagery_date_iso(payload: dict[str, Any]) -> Optional[str]:
    """Capture date of the imagery behind a buildingInsights response.

    Solar returns ``imageryDate`` as ``{year, month, day}``; we render it as
    an ISO ``YYYY-MM-DD`` string for display.
    """
    d = payload.get("imageryDate") or {}
    year = d.get("year")
    if not year:
        return None
    month = int(d.get("month") or 1)
    day = int(d.get("day") or 1)
    return f"{int(year):04d}-{month:02d}-{day:02d}"


def imagery_quality(payload: dict[str, Any]) -> Optional[str]:
    """Solar ``imageryQuality`` (HIGH / MEDIUM / LOW), if present."""
    return payload.get("imageryQuality")


class SolarClient:
    """Thin HTTP client. The ``http_get`` hook is injectable for tests."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = SOLAR_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        http_get: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_get = http_get

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise SolarError(
                "no API key; set GOOGLE_MAPS_API_KEY or pass api_key="
            )
        params = {**params, "key": self.api_key}

        if self._http_get is not None:
            return self._http_get(url, params=params, timeout=self.timeout)

        import requests  # imported lazily so the engine has no dep

        resp = requests.get(url, params=params, timeout=self.timeout)
        if resp.status_code == 404:
            raise CoverageError(f"no Solar coverage (404) for {params!r}")
        if resp.status_code != 200:
            raise SolarError(f"Solar API {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def building_insights(
        self, lat: float, lng: float, *, quality: str = "HIGH"
    ) -> dict[str, Any]:
        """Raw ``buildingInsights:findClosest`` payload for a coordinate."""
        url = f"{self.base_url}/buildingInsights:findClosest"
        return self._get(
            url,
            {
                "location.latitude": lat,
                "location.longitude": lng,
                "requiredQuality": quality,
            },
        )

    def roof_report(
        self, lat: float, lng: float, *, waste_pct: float | None = None
    ) -> RoofReport:
        """Geometry -> :class:`RoofReport` for a coordinate."""
        payload = self.building_insights(lat, lng)
        return parse_building_insights(payload, waste_pct=waste_pct)

    def data_layers(
        self, lat: float, lng: float, radius_m: float = 50.0
    ) -> dict[str, Any]:
        """``dataLayers:get`` — signed GeoTIFF URLs (expire ~1h)."""
        url = f"{self.base_url}/dataLayers:get"
        return self._get(
            url,
            {
                "location.latitude": lat,
                "location.longitude": lng,
                "radiusMeters": radius_m,
                "requiredQuality": "HIGH",
            },
        )
