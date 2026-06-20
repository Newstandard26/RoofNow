"""Roof & wall measurement formulas.

Pure functions + small value objects. Input is geometry (areas, runs,
pitches); output is numbers (squares, lengths, wall areas). No I/O.

All public area inputs/outputs are in **square feet** and lengths in
**feet** unless a name says otherwise. Solar API returns metric, so convert
at the boundary with ``SQM_TO_SQFT`` / :meth:`Pitch.from_degrees`.

Formula reference (from the project spec):

    roofing_square   = 100 sq ft
    squares          = sloped_area_sqft / 100
    pitch_degrees    = atan(rise/run) * 180/pi
    percent_slope    = (rise/run) * 100
    pitch_multiplier = sqrt(1 + (rise/run)^2)        # plan -> sloped
    sloped_area      = footprint_area * pitch_multiplier
    hip_valley_factor= sqrt((rise/run)^2 + 2)        # diagonal members
    rake_length      = horizontal_run * pitch_multiplier
    order_area       = roof_area * (1 + waste_pct)
    gross_wall_area  = 2 * height * (length + width)  # rectangular footprint
    gable_triangle   = (gable_width * gable_height) / 2
    net_siding_area  = gross_wall_area - sum(openings)
    height_shadow    = shadow_length * tan(sun_elevation)   # sanity only
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

# --------------------------------------------------------------------------
# Constants & unit conversions
# --------------------------------------------------------------------------

ROOFING_SQUARE_SQFT: float = 100.0
"""One roofing "square" = 100 square feet of roof surface."""

SQM_TO_SQFT: float = 10.7639104167
"""Square meters -> square feet (Solar API returns m²)."""

M_TO_FT: float = 3.280839895
"""Meters -> feet."""

# Standard run for X/12 pitch notation.
STANDARD_RUN: float = 12.0


def sqm_to_sqft(area_m2: float) -> float:
    """Convert square meters to square feet."""
    return area_m2 * SQM_TO_SQFT


def m_to_ft(length_m: float) -> float:
    """Convert meters to feet."""
    return length_m * M_TO_FT


# --------------------------------------------------------------------------
# Pitch — the slope of a roof facet
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Pitch:
    """Roof slope, stored canonically as rise-over-run.

    Construct from whichever representation a data source gives you:
    ``Pitch(rise=6, run=12)``, :meth:`from_degrees` (Solar API), or
    :meth:`from_x12` (contractor "6/12" notation).
    """

    rise: float
    run: float = STANDARD_RUN

    def __post_init__(self) -> None:
        if self.run <= 0:
            raise ValueError("run must be positive")
        if self.rise < 0:
            raise ValueError("rise must be non-negative")

    # -- constructors ------------------------------------------------------

    @classmethod
    def from_degrees(cls, degrees: float) -> "Pitch":
        """Build from a slope angle in degrees (Solar API ``pitchDegrees``).

        Uses the spec convention ``run=12, rise=12*tan(radians(deg))`` so the
        result reads naturally as an X/12 pitch.
        """
        if not 0 <= degrees < 90:
            raise ValueError("degrees must be in [0, 90)")
        rise = STANDARD_RUN * math.tan(math.radians(degrees))
        return cls(rise=rise, run=STANDARD_RUN)

    @classmethod
    def from_x12(cls, rise: float) -> "Pitch":
        """Build from contractor 'rise/12' notation, e.g. ``from_x12(6)``."""
        return cls(rise=rise, run=STANDARD_RUN)

    # -- representations ---------------------------------------------------

    @property
    def ratio(self) -> float:
        """rise / run."""
        return self.rise / self.run

    @property
    def degrees(self) -> float:
        """Slope angle in degrees."""
        return math.degrees(math.atan(self.ratio))

    @property
    def percent_slope(self) -> float:
        """Slope as a percentage: (rise/run) * 100."""
        return self.ratio * 100.0

    @property
    def x12(self) -> float:
        """Rise per 12 units of run (the 'X' in X/12)."""
        return self.ratio * STANDARD_RUN

    @property
    def multiplier(self) -> float:
        """Plan-area -> sloped-area multiplier: sqrt(1 + (rise/run)^2)."""
        return math.sqrt(1.0 + self.ratio**2)

    @property
    def hip_valley_factor(self) -> float:
        """Diagonal-member factor: sqrt((rise/run)^2 + 2)."""
        return math.sqrt(self.ratio**2 + 2.0)

    def label(self) -> str:
        """Human label like '6/12'."""
        x = self.x12
        return f"{round(x)}/12" if abs(x - round(x)) < 0.05 else f"{x:.1f}/12"


# Convenience free functions mirroring the spec names ----------------------


def pitch_multiplier(rise: float, run: float = STANDARD_RUN) -> float:
    """sqrt(1 + (rise/run)^2) — convert plan area to sloped area."""
    return Pitch(rise=rise, run=run).multiplier


def hip_valley_factor(rise: float, run: float = STANDARD_RUN) -> float:
    """sqrt((rise/run)^2 + 2) — length factor for hips & valleys."""
    return Pitch(rise=rise, run=run).hip_valley_factor


# --------------------------------------------------------------------------
# Roof area / squares / lengths
# --------------------------------------------------------------------------


def sloped_area(footprint_area: float, pitch: Pitch) -> float:
    """Sloped (surface) roof area from a plan/footprint area."""
    if footprint_area < 0:
        raise ValueError("footprint_area must be non-negative")
    return footprint_area * pitch.multiplier


def squares(sloped_area_sqft: float) -> float:
    """Roofing squares (raw, un-rounded) for a sloped area in sqft."""
    return sloped_area_sqft / ROOFING_SQUARE_SQFT


def rake_length(horizontal_run: float, pitch: Pitch) -> float:
    """True (sloped) rake length from its horizontal run."""
    if horizontal_run < 0:
        raise ValueError("horizontal_run must be non-negative")
    return horizontal_run * pitch.multiplier


def order_area(roof_area: float, waste_pct: float) -> float:
    """Material order area including waste, e.g. waste_pct=0.10 for 10%."""
    if waste_pct < 0:
        raise ValueError("waste_pct must be non-negative")
    return roof_area * (1.0 + waste_pct)


def order_squares(sloped_area_sqft: float, waste_pct: float) -> int:
    """Whole squares to order, rounded UP, including waste."""
    return math.ceil(squares(order_area(sloped_area_sqft, waste_pct)))


# --------------------------------------------------------------------------
# Waste factor suggestions
# --------------------------------------------------------------------------


class WasteCategory(str, Enum):
    """Roof complexity buckets and their conventional waste factors."""

    SIMPLE_GABLE = "simple_gable"
    TYPICAL = "typical"
    COMPLEX = "complex"
    TILE = "tile"


# Spec conventions: simple gable ~5%, typical 10-15%, complex 15-20%,
# tile 15-20%. We pick a representative midpoint for ordering.
_WASTE_PCT = {
    WasteCategory.SIMPLE_GABLE: 0.05,
    WasteCategory.TYPICAL: 0.12,
    WasteCategory.COMPLEX: 0.18,
    WasteCategory.TILE: 0.18,
}


def suggest_waste_pct(category: WasteCategory) -> float:
    """Suggested waste fraction for a complexity category."""
    return _WASTE_PCT[category]


def suggest_waste_from_facets(num_facets: int, *, tile: bool = False) -> float:
    """Heuristic waste factor from facet count (a proxy for complexity)."""
    if tile:
        return _WASTE_PCT[WasteCategory.TILE]
    if num_facets <= 2:
        return _WASTE_PCT[WasteCategory.SIMPLE_GABLE]
    if num_facets <= 6:
        return _WASTE_PCT[WasteCategory.TYPICAL]
    return _WASTE_PCT[WasteCategory.COMPLEX]


# --------------------------------------------------------------------------
# Walls
# --------------------------------------------------------------------------


def gross_wall_area(length: float, width: float, height: float) -> float:
    """Gross wall area of a rectangular footprint: 2*h*(l+w)."""
    for name, v in (("length", length), ("width", width), ("height", height)):
        if v < 0:
            raise ValueError(f"{name} must be non-negative")
    return 2.0 * height * (length + width)


def wall_area_from_perimeter(perimeter: float, height: float) -> float:
    """Gross wall area from an arbitrary footprint perimeter * eave height."""
    if perimeter < 0 or height < 0:
        raise ValueError("perimeter and height must be non-negative")
    return perimeter * height


def gable_triangle_area(gable_width: float, gable_height: float) -> float:
    """Area of a single gable triangle: (width * height) / 2."""
    if gable_width < 0 or gable_height < 0:
        raise ValueError("gable dimensions must be non-negative")
    return (gable_width * gable_height) / 2.0


def net_siding_area(
    gross_area: float,
    openings: Iterable[float] = (),
    waste_pct: float = 0.0,
) -> float:
    """Net siding area = (gross - openings) * (1 + waste_pct).

    ``openings`` is each window/door area in sqft. ~0.10 is a common siding
    waste factor. Never returns less than zero.
    """
    total_openings = sum(openings)
    net = max(0.0, gross_area - total_openings)
    return order_area(net, waste_pct)


# --------------------------------------------------------------------------
# Sanity checks / photogrammetry helpers
# --------------------------------------------------------------------------


def height_from_shadow(shadow_length: float, sun_elevation_deg: float) -> float:
    """Object height from shadow length: shadow * tan(sun_elevation).

    Sanity-check only — never a primary measurement.
    """
    if not 0 < sun_elevation_deg < 90:
        raise ValueError("sun_elevation_deg must be in (0, 90)")
    return shadow_length * math.tan(math.radians(sun_elevation_deg))


def ground_sample_distance(
    altitude: float, pixel_pitch: float, focal_length: float
) -> float:
    """GSD = (altitude * pixel_pitch) / focal_length (consistent units in)."""
    if focal_length <= 0:
        raise ValueError("focal_length must be positive")
    return (altitude * pixel_pitch) / focal_length


# --------------------------------------------------------------------------
# Facet measurement & roof summary
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FacetMeasurement:
    """Measured result for a single roof facet/segment."""

    pitch: Pitch
    azimuth_deg: float
    footprint_area_sqft: float
    sloped_area_sqft: float
    squares: float
    confidence: float = 1.0
    source: str = "unknown"

    @property
    def needs_qa(self) -> bool:
        """True when confidence is low enough to warrant human review."""
        return self.confidence < 0.6


def measure_facet(
    *,
    footprint_area_sqft: float,
    pitch: Pitch,
    azimuth_deg: float,
    confidence: float = 1.0,
    source: str = "unknown",
) -> FacetMeasurement:
    """Compute the measured quantities for one facet from its plan geometry."""
    sloped = sloped_area(footprint_area_sqft, pitch)
    return FacetMeasurement(
        pitch=pitch,
        azimuth_deg=azimuth_deg % 360.0,
        footprint_area_sqft=footprint_area_sqft,
        sloped_area_sqft=sloped,
        squares=squares(sloped),
        confidence=confidence,
        source=source,
    )


@dataclass
class RoofReport:
    """Aggregated roof measurements over all facets."""

    facets: list[FacetMeasurement] = field(default_factory=list)
    waste_pct: float = 0.0

    @property
    def total_footprint_sqft(self) -> float:
        return sum(f.footprint_area_sqft for f in self.facets)

    @property
    def total_sloped_sqft(self) -> float:
        return sum(f.sloped_area_sqft for f in self.facets)

    @property
    def total_squares(self) -> float:
        return squares(self.total_sloped_sqft)

    @property
    def order_squares(self) -> int:
        """Whole squares to order including waste, rounded up."""
        return math.ceil(squares(order_area(self.total_sloped_sqft, self.waste_pct)))

    @property
    def predominant_pitch(self) -> Pitch | None:
        """Pitch of the facet contributing the most sloped area."""
        if not self.facets:
            return None
        return max(self.facets, key=lambda f: f.sloped_area_sqft).pitch

    @property
    def min_confidence(self) -> float:
        return min((f.confidence for f in self.facets), default=1.0)

    @property
    def facets_needing_qa(self) -> list[FacetMeasurement]:
        return [f for f in self.facets if f.needs_qa]


def summarize_roof(
    facets: Sequence[FacetMeasurement],
    waste_pct: float | None = None,
) -> RoofReport:
    """Build a :class:`RoofReport`; auto-suggests waste if not given."""
    if waste_pct is None:
        waste_pct = suggest_waste_from_facets(len(facets))
    return RoofReport(facets=list(facets), waste_pct=waste_pct)
