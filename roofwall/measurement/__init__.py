"""Pure measurement engine — no I/O, no external services.

Build & test this FIRST. Everything else (Solar API, LiDAR, drone
photogrammetry) is just a way to produce the geometry that flows into
these functions.
"""

from roofwall.measurement.engine import (
    ROOFING_SQUARE_SQFT,
    SQM_TO_SQFT,
    FacetMeasurement,
    Pitch,
    RoofReport,
    WasteCategory,
    gable_triangle_area,
    gross_wall_area,
    height_from_shadow,
    hip_valley_factor,
    measure_facet,
    net_siding_area,
    order_area,
    pitch_multiplier,
    rake_length,
    sloped_area,
    squares,
    summarize_roof,
    suggest_waste_pct,
)

__all__ = [
    "ROOFING_SQUARE_SQFT",
    "SQM_TO_SQFT",
    "FacetMeasurement",
    "Pitch",
    "RoofReport",
    "WasteCategory",
    "gable_triangle_area",
    "gross_wall_area",
    "height_from_shadow",
    "hip_valley_factor",
    "measure_facet",
    "net_siding_area",
    "order_area",
    "pitch_multiplier",
    "rake_length",
    "sloped_area",
    "squares",
    "summarize_roof",
    "suggest_waste_pct",
]
