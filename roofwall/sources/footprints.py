"""Building footprints (fallback geometry source).

Microsoft / Google open building footprints provide the polygon used to
crop LiDAR and to derive wall perimeters when the Solar mask is absent.
Phase 2 — not yet implemented.
"""

from __future__ import annotations

from typing import Sequence

from roofwall.measurement.geometry import Point


def footprint_for(lat: float, lng: float) -> Sequence[Point]:
    """Nearest open-data building footprint polygon for a coordinate."""
    raise NotImplementedError(
        "Footprint lookup is Phase 2 (Microsoft/Google open buildings)."
    )
