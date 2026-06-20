"""LiDAR plane-fit pipeline, validated against synthetic point clouds."""

import numpy as np
import pytest

from roofwall.measurement.engine import Pitch
from roofwall.sources.lidar import (
    Plane,
    facets_from_points,
    fit_plane,
    plan_area_units2,
    segment_planes,
)


def _plane_points(normal, d, n=400, extent=10.0, noise=0.0, seed=1):
    """Sample points on plane normal·x = d over an x,y grid."""
    rng = np.random.default_rng(seed)
    xy = rng.uniform(-extent, extent, size=(n, 2))
    nx, ny, nz = normal
    z = (d - nx * xy[:, 0] - ny * xy[:, 1]) / nz
    pts = np.column_stack([xy, z])
    if noise:
        pts[:, 2] += rng.normal(0, noise, size=n)
    return pts


def test_fit_plane_horizontal():
    pts = _plane_points((0, 0, 1), 5.0)
    plane = fit_plane(pts)
    assert plane.pitch_degrees == pytest.approx(0.0, abs=1e-6)
    assert plane.rms == pytest.approx(0.0, abs=1e-9)


def test_fit_plane_recovers_pitch():
    # A plane sloping in +x: z = 0.5*x  -> normal ~ (-0.5,0,1).
    # rise/run = 0.5 -> ~6/12 -> 26.57 deg.
    pts = _plane_points((-0.5, 0.0, 1.0), 0.0)
    plane = fit_plane(pts)
    assert plane.pitch_degrees == pytest.approx(26.565, abs=1e-2)
    assert plane.pitch().x12 == pytest.approx(6.0, abs=0.02)


def test_azimuth_south_facing():
    # Roof descending toward south (-y): z increases with y => normal tilts
    # north; facing/azimuth should read ~180 (south) for a south slope.
    # Build a plane that descends to +y (north) and check it faces north(0).
    pts = _plane_points((0.0, 1.0, 1.0), 0.0)  # z = -y, descends to +y
    plane = fit_plane(pts)
    assert plane.azimuth_degrees == pytest.approx(0.0, abs=1.0)


def test_azimuth_cardinal_directions():
    cases = {
        (0.0, 1.0): 0.0,    # normal tilts +y -> faces N
        (1.0, 0.0): 90.0,   # faces E
        (0.0, -1.0): 180.0, # faces S
        (-1.0, 0.0): 270.0, # faces W
    }
    for (nx, ny), expected in cases.items():
        pts = _plane_points((nx, ny, 1.0), 0.0)
        plane = fit_plane(pts)
        assert plane.azimuth_degrees == pytest.approx(expected, abs=1.0)


def test_plan_area_of_square_patch():
    # 20x20 horizontal patch -> plan area ~400.
    pts = _plane_points((0, 0, 1), 0.0, n=2000, extent=10.0)
    assert plan_area_units2(pts) == pytest.approx(400.0, rel=0.05)


def test_segment_two_facet_gable():
    # Two opposing 6/12 planes meeting at a ridge -> a gable.
    left = _plane_points((-0.5, 0, 1), 0.0, n=500, extent=8.0, noise=0.01, seed=2)
    right = _plane_points((0.5, 0, 1), 0.0, n=500, extent=8.0, noise=0.01, seed=3)
    cloud = np.vstack([left, right])
    planes = segment_planes(cloud, dist_threshold=0.1, min_inliers=100, seed=7)
    assert len(planes) >= 2
    pitches = sorted(p.pitch_degrees for _, p in planes[:2])
    assert all(abs(pd - 26.565) < 1.5 for pd in pitches)


def test_facets_from_points_gable():
    left = _plane_points((-0.5, 0, 1), 0.0, n=500, extent=8.0, noise=0.01, seed=2)
    right = _plane_points((0.5, 0, 1), 0.0, n=500, extent=8.0, noise=0.01, seed=3)
    cloud = np.vstack([left, right])
    facets = facets_from_points(cloud, dist_threshold=0.1, min_inliers=100, seed=7)
    assert len(facets) >= 2
    for f in facets[:2]:
        assert f.pitch.x12 == pytest.approx(6.0, abs=0.1)
        assert f.source == "lidar"
        assert 0.0 <= f.confidence <= 1.0


def test_low_confidence_flag_on_noisy_fit():
    noisy = _plane_points((-0.5, 0, 1), 0.0, n=600, extent=8.0, noise=0.12, seed=5)
    facets = facets_from_points(noisy, dist_threshold=0.15, min_inliers=100, seed=1)
    assert facets
    # High noise relative to threshold should pull confidence down.
    assert facets[0].confidence < 1.0


def test_fit_plane_rejects_too_few_points():
    with pytest.raises(ValueError):
        fit_plane(np.zeros((2, 3)))
