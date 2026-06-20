"""FastAPI app exposing the measurement pipeline.

Run:  uvicorn roofwall.api.main:app --reload   (needs the 'api' extra)

    GET /measure?address=...                 -> JSON report
    GET /measure?lat=..&lng=..&waste=0.10    -> JSON report
"""

from __future__ import annotations

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover - optional dep
    raise RuntimeError(
        "API layer needs the 'api' extra: pip install roofwall[api]"
    ) from exc

from roofwall.report.render import report_to_dict
from roofwall.sources.geocode import GeocodeError, Geocoder
from roofwall.sources.solar import CoverageError, SolarClient, SolarError

app = FastAPI(title="roofwall", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/measure")
def measure(
    address: str | None = Query(default=None),
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    waste: float | None = Query(default=None),
) -> dict:
    formatted = address
    if lat is None or lng is None:
        if not address:
            raise HTTPException(400, "provide address, or lat and lng")
        try:
            geo = Geocoder().geocode(address)
        except GeocodeError as exc:
            raise HTTPException(422, f"geocode failed: {exc}") from exc
        lat, lng, formatted = geo.lat, geo.lng, geo.formatted_address

    try:
        report = SolarClient().roof_report(lat, lng, waste_pct=waste)
    except CoverageError as exc:
        raise HTTPException(404, "no Solar coverage; LiDAR fallback pending") from exc
    except SolarError as exc:
        raise HTTPException(502, f"Solar API error: {exc}") from exc

    return report_to_dict(report, meta={"lat": lat, "lng": lng, "address": formatted})
