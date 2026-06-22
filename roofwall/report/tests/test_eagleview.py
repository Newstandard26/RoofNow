"""EagleView report sections, benchmarked to 8656 Scott Lane."""

from roofwall.measurement.engine import Pitch, measure_facet
from roofwall.report.eagleview import (
    areas_per_pitch,
    eagleview_sections,
    predominant_pitch,
    round_up_third,
    snap_pitch_x12,
    structure_complexity,
    suggested_waste_pct,
    waste_table,
)


def _facets_6x12(total_sloped=3006.0, n=14):
    """n facets, all ~6/12 (some at 6.4/6.6 to test snapping), summing to total."""
    each = total_sloped / n
    out = []
    for i in range(n):
        x = 6.0 + (0.4 if i % 2 else -0.3)        # 6.4 / 5.7 -> snap to 6
        # back out a footprint so sloped_area == each for this pitch
        p = Pitch.from_x12(x)
        out.append(measure_facet(footprint_area_sqft=each / p.multiplier,
                                 pitch=p, azimuth_deg=(i * 47) % 360))
    return out


def test_snap_pitch_to_standard():
    assert snap_pitch_x12(6.4) == 6
    assert snap_pitch_x12(6.6) == 7
    assert snap_pitch_x12(0.2) == 0


def test_predominant_pitch_is_six_twelve():
    facets = _facets_6x12()
    assert predominant_pitch(facets) == "6/12"
    rows = areas_per_pitch(facets)
    assert rows[0]["pitch"] == "6/12"
    assert rows[0]["percent"] == 100.0          # whole roof at 6/12


def test_round_up_third():
    assert round_up_third(36.37) == 110 / 3     # 36.666...
    assert round_up_third(30.0) == 30.0


def test_structure_complexity_normal_for_scott_lane():
    assert structure_complexity(14, 94.0) == "Normal"
    assert structure_complexity(3, 0.0) == "Simple"
    assert structure_complexity(20, 30.0) == "Complex"
    assert structure_complexity(6, 200.0) == "Complex"


def test_waste_table_suggested_matches_eagleview():
    # 3,006 sqft @ 21% waste -> ~36.66 squares, suggested row flagged.
    rows = waste_table(3006.0, suggested_waste_pct("Normal"))
    by_pct = {r["waste_pct"]: r for r in rows}
    assert by_pct[21]["suggested"] is True
    assert abs(by_pct[21]["squares"] - 36.66) < 0.1
    assert sum(1 for r in rows if r["suggested"]) == 1


def test_eagleview_sections_shape():
    facets = _facets_6x12()
    secs = eagleview_sections(facets, 3006.0,
                              line_lengths={"valley": {"count": 5, "length_ft": 94.0}})
    assert secs["predominant_pitch"] == "6/12"
    assert secs["structure_complexity"] == "Normal"
    assert secs["suggested_waste_pct"] == 21
    assert any(r["suggested"] for r in secs["waste_table"])
