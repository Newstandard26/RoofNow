"""Data-source adapters that produce geometry for the measurement engine.

Each source converts an external response into the engine's value objects
(``FacetMeasurement`` / ``RoofReport``). Sources are tried in priority
order: Solar API (Phase 1) -> LiDAR (Phase 2) -> photogrammetry (Phase 3).
"""

from roofwall.sources.solar import (
    CoverageError,
    SolarClient,
    SolarError,
    parse_building_insights,
)

__all__ = [
    "CoverageError",
    "SolarClient",
    "SolarError",
    "parse_building_insights",
]
