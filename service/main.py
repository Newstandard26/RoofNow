"""roofwall-cv — DSM -> facet-polygons recovery service.

The heavy geospatial stack (~400 MB: numpy/scipy/scikit-image + GDAL/PROJ via
rasterio/pyproj) can't fit in a Vercel function, so recovery runs here (Cloud
Run / Render / Fly). The RoofNow app calls ``GET /facets?lat=&lng=`` and merges
the returned ``line_lengths`` into its report — set ``ROOFWALL_CV_URL`` on the
Vercel project to this service's URL.

Run locally:  uvicorn service.main:app --reload
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query

from roofwall.cv.solar_dsm import build_model_from_solar_dsm

app = FastAPI(title="roofwall-cv", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "has_key": bool(os.environ.get("GOOGLE_MAPS_API_KEY"))}


@app.get("/facets")
def facets(lat: float = Query(...), lng: float = Query(...)) -> dict:
    """Recover real facet polygons + Length Diagram for a coordinate."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise HTTPException(500, "GOOGLE_MAPS_API_KEY not set on the cv service")
    try:
        model = build_model_from_solar_dsm(lat, lng, key)
    except Exception as exc:  # noqa: BLE001 - report, don't 500 the caller
        return {"model": None, "line_lengths": None, "recovery_status": f"error: {exc}"}
    return {
        "model": model.to_dict(),
        "line_lengths": model.line_lengths(),
        "recovery_status": f"ok:{len(model.facets)}",
    }
