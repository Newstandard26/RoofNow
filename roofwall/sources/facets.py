"""Facet service: address/coords -> BuildingModel (M1 plumbing).

M1 proves the seam end-to-end: this returns a real, watertight ``BuildingModel``
(the cross-gable fixture) whose facets flow through snapping + the edge
classifier to produce true line lengths. M2 swaps the synthetic model for the
Solar-DSM pipeline (:mod:`roofwall.cv.solar_dsm`) without changing this contract.
"""

from __future__ import annotations

import os
from typing import Optional

from roofwall.measurement.edges import cross_gable
from roofwall.model import BuildingModel, Origin

# Arbitrary local-frame origin for the synthetic sample.
_SAMPLE_ORIGIN = Origin(lat=42.3196, lng=-89.0392)  # Machesney Park, IL area


def sample_building_model() -> BuildingModel:
    """A known watertight cross-gable as a BuildingModel (3 ridges, 2 valleys)."""
    return BuildingModel.from_edge_facets(
        cross_gable(),
        origin=_SAMPLE_ORIGIN,
        source="synthetic",
        notes="M1 plumbing fixture (cross-gable). Not a real building.",
    )


def building_model_for(
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    *,
    key: Optional[str] = None,
) -> BuildingModel:
    """Return a BuildingModel for a location.

    Until the Solar-DSM raster pipeline (M2) is deployed, this returns the
    synthetic sample with a note — it does NOT fabricate a real roof outline.
    """
    key = key or os.environ.get("GOOGLE_MAPS_API_KEY")
    # M2 hook (intentionally not active here — raster libs/downloads absent):
    #   if key and (address or (lat and lng)):
    #       return roofwall.cv.solar_dsm.build_model_from_solar_dsm(lat, lng, key)
    model = sample_building_model()
    if address or (lat is not None and lng is not None):
        model.notes = (
            "Boundary recovery (M2 Solar-DSM) not yet deployed; returning the "
            "synthetic sample. Real per-facet polygons require the raster pipeline."
        )
    return model
