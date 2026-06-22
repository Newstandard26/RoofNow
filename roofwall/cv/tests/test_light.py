"""Lightweight recovery round-trip (numpy + tifffile + contourpy, no GDAL)."""
import io
import math

import pytest

pytest.importorskip("tifffile")
pytest.importorskip("contourpy")

import numpy as np  # noqa: E402
import tifffile  # noqa: E402

from roofwall.cv.light import _R, build_model_light  # noqa: E402
from roofwall.cv.recover import abc_from_normal, plane_z  # noqa: E402
from roofwall.cv.synth import _point_in_poly2d  # noqa: E402
from roofwall.measurement.edges import hip_roof  # noqa: E402
from roofwall.measurement.engine import M_TO_FT  # noqa: E402

LAT0, LON0 = 42.3483, -89.0421
RES_FT = 0.5


def _merc(lon, lat):
    return (math.radians(lon) * _R,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _R)


def _ft_to_lonlat(xf, yf):
    coslat = math.cos(math.radians(LAT0))
    return (LON0 + math.degrees((xf / M_TO_FT) / (_R * coslat)),
            LAT0 + math.degrees((yf / M_TO_FT) / _R))


def _tif(arr, px, ulx, uly):
    buf = io.BytesIO()
    tifffile.imwrite(buf, arr, extratags=[
        (33550, "d", 3, (px, px, 0.0), True),
        (33922, "d", 6, (0.0, 0.0, 0.0, ulx, uly, 0.0), True),
    ])
    return buf.getvalue()


def _synth(facets, noise_ft=0.0):
    planes = [abc_from_normal(f.normal, f.verts[0]) for f in facets]
    mxs, mys = [], []
    for f in facets:
        for v in f.verts:
            lon, lat = _ft_to_lonlat(v[0], v[1])
            mx, my = _merc(lon, lat)
            mxs.append(mx); mys.append(my)
    px = (RES_FT / M_TO_FT) / math.cos(math.radians(LAT0))
    xmin, xmax = min(mxs) - 4 * px, max(mxs) + 4 * px
    ymin, ymax = min(mys) - 4 * px, max(mys) + 4 * px
    ncols = int(math.ceil((xmax - xmin) / px)) + 1
    nrows = int(math.ceil((ymax - ymin) / px)) + 1
    ulx, uly = xmin, ymax
    coslat = math.cos(math.radians(LAT0))
    dsm = np.zeros((nrows, ncols), "float32")
    mask = np.zeros((nrows, ncols), "uint8")
    for r in range(nrows):
        for c in range(ncols):
            X = ulx + (c + 0.5) * px
            Y = uly - (r + 0.5) * px
            lon = math.degrees(X / _R)
            lat = math.degrees(2 * math.atan(math.exp(Y / _R)) - math.pi / 2)
            xf = math.radians(lon - LON0) * coslat * _R * M_TO_FT
            yf = math.radians(lat - LAT0) * _R * M_TO_FT
            bi, bz = -1, -1e18
            for i, f in enumerate(facets):
                if _point_in_poly2d(xf, yf, f.verts):
                    z = plane_z(planes[i], xf, yf)
                    if z > bz:
                        bz, bi = z, i
            if bi >= 0:
                dsm[r, c] = bz / M_TO_FT
                mask[r, c] = 1
    if noise_ft:
        rng = np.random.default_rng(3)
        dsm = dsm + (mask * rng.normal(0, noise_ft / M_TO_FT, dsm.shape)).astype("float32")
    segs = []
    for f in facets:
        nx, ny, nz = f.normal
        cx, cy, cz = f.cen
        lon, lat = _ft_to_lonlat(cx, cy)
        segs.append({
            "pitchDegrees": math.degrees(math.acos(min(1.0, abs(nz)))),
            "azimuthDegrees": (math.degrees(math.atan2(nx, ny)) + 360) % 360,
            "center": {"latitude": lat, "longitude": lon},
            "planeHeightAtCenterMeters": cz / M_TO_FT,
        })
    return _tif(dsm, px, ulx, uly), _tif(mask, px, ulx, uly), segs


def test_read_geotiff_model_transformation():
    # Some DSM GeoTIFFs georeference via a ModelTransformation matrix (tag 34264)
    # rather than ModelPixelScale + ModelTiepoint. The reader must handle both.
    from roofwall.cv.light import _read_geotiff

    arr = np.arange(12, dtype="float32").reshape(3, 4)
    sx, sy, ox, oy = 0.25, 0.25, 1000.0, 2000.0
    matrix = (sx, 0.0, 0.0, ox,
              0.0, -sy, 0.0, oy,
              0.0, 0.0, 0.0, 0.0,
              0.0, 0.0, 0.0, 1.0)
    buf = io.BytesIO()
    tifffile.imwrite(buf, arr, extratags=[(34264, "d", 16, matrix, True)])
    rarr, rsx, rsy, rox, roy, epsg = _read_geotiff(buf.getvalue())
    assert (rsx, rsy, rox, roy) == (sx, sy, ox, oy)
    assert epsg is None
    assert rarr.shape == (3, 4)


def test_utm_inverse_matches_pyproj():
    # The Solar DSM is WGS84 UTM (e.g. EPSG:32610). Validate the pure-Python
    # Transverse-Mercator inverse against pyproj across a few in-zone points.
    pyproj = pytest.importorskip("pyproj")
    from roofwall.cv.light import _projector

    fwd = pyproj.Transformer.from_crs(4326, 32610, always_xy=True)  # zone 10N
    inv = _projector(32610)
    for lat, lon in [(37.4220, -122.0841), (40.0, -123.0), (45.0, -121.5)]:
        e, n = fwd.transform(lon, lat)
        rlon, rlat = inv(e, n)
        assert abs(rlon - lon) < 1e-6
        assert abs(rlat - lat) < 1e-6


def test_projector_rejects_unknown_crs():
    from roofwall.cv.light import _projector
    with pytest.raises(ValueError, match="EPSG:2193"):
        _projector(2193)  # NZ Transverse Mercator — not supported


def test_poly_area_sqft():
    from roofwall.cv.light import _poly_area_sqft
    square = [(0, 0, 0), (10, 0, 1), (10, 10, 1), (0, 10, 0)]  # 10x10 footprint
    assert abs(_poly_area_sqft(square) - 100.0) < 1e-6


def test_merge_priors_collapses_near_duplicates():
    from roofwall.cv.light import _merge_priors

    base = (0.30, -0.10, 12.0)
    priors = [
        {"id": "a", "abc": base},
        {"id": "b", "abc": (0.31, -0.09, 12.3)},   # near-duplicate of a -> merged
        {"id": "c", "abc": (-0.30, 0.10, 11.5)},   # different plane
        {"id": "d", "abc": (0.30, -0.10, 22.0)},   # same slope, +10 ft -> distinct
    ]
    merged = _merge_priors(priors)
    assert len(merged) == 3
    assert merged[0]["id"] == "a"  # first of the merged pair is kept


def test_oversegmented_hip_recovers_clean_facets():
    # Reproduce Google Solar over-segmentation: triple each segment with small
    # pitch/azimuth jitter. Without prior-merging these near-duplicate planes
    # fragment the facets; with it we still recover the 4 clean hip facets.
    facets = hip_roof(40, 24, 6)
    dsm_b, mask_b, segs = _synth(facets)
    rng = np.random.default_rng(1)
    over = []
    for s in segs:
        for _ in range(3):
            j = dict(s)
            j["pitchDegrees"] = s["pitchDegrees"] + float(rng.uniform(-0.8, 0.8))
            j["azimuthDegrees"] = s["azimuthDegrees"] + float(rng.uniform(-0.8, 0.8))
            over.append(j)
    payload = {"solarPotential": {"roofSegmentStats": over}}

    class FakeClient:
        def building_insights(self, lat, lng):
            return payload

        def data_layers(self, lat, lng, radius_m=50.0):
            return {"dsmUrl": "http://x/dsm", "maskUrl": "http://x/mask"}

    def fetch(url, key):
        return dsm_b if url.endswith("dsm") else mask_b

    model = build_model_light(LAT0, LON0, "k", client=FakeClient(), fetch=fetch)
    assert len(model.facets) == 4  # 12 jittered segments -> 4 physical planes
    ll = model.line_lengths()
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4


def test_noisy_priors_refine_to_clean_facets():
    # Solar priors are approximate. Perturb pitch/azimuth/height noticeably so a
    # *fixed* plane only grazes the roof (-> noodly fragments); the EM refit must
    # still recover the 4 compact hip facets with correct topology.
    facets = hip_roof(40, 24, 6)
    dsm_b, mask_b, segs = _synth(facets)
    rng = np.random.default_rng(7)
    noisy = []
    for s in segs:
        j = dict(s)
        j["pitchDegrees"] = s["pitchDegrees"] + float(rng.uniform(-3, 3))
        j["azimuthDegrees"] = s["azimuthDegrees"] + float(rng.uniform(-6, 6))
        j["planeHeightAtCenterMeters"] = s["planeHeightAtCenterMeters"] + float(
            rng.uniform(-0.6, 0.6))
        noisy.append(j)
    payload = {"solarPotential": {"roofSegmentStats": noisy}}

    class FakeClient:
        def building_insights(self, lat, lng):
            return payload

        def data_layers(self, lat, lng, radius_m=50.0):
            return {"dsmUrl": "http://x/dsm", "maskUrl": "http://x/mask"}

    def fetch(url, key):
        return dsm_b if url.endswith("dsm") else mask_b

    model = build_model_light(LAT0, LON0, "k", client=FakeClient(), fetch=fetch)
    assert len(model.facets) == 4
    ll = model.line_lengths()
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4
    assert ll["eave"]["count"] == 4


def test_smooth_labels_removes_salt_and_pepper():
    from roofwall.cv.light import _smooth_labels
    clean = np.zeros((24, 24), dtype=int)
    clean[:, 12:] = 1
    rng = np.random.default_rng(0)
    noisy = np.where(rng.random((24, 24)) < 0.18, 1 - clean, clean)
    smoothed = _smooth_labels(noisy, 2, iters=3)
    assert (smoothed == clean).mean() > 0.97        # interleaving cleaned up


def test_noisy_dsm_recovers_clean_lines():
    # A noisy DSM makes similar planes interleave (salt-and-pepper) and the
    # residual cutoff punch holes -> inflated/over-counted edges. fill + smooth
    # must keep the hip topology clean and the lengths sane.
    facets = hip_roof(40, 24, 6)
    dsm_b, mask_b, segs = _synth(facets, noise_ft=0.4)
    payload = {"solarPotential": {"roofSegmentStats": segs}}

    class FakeClient:
        def building_insights(self, lat, lng):
            return payload

        def data_layers(self, lat, lng, radius_m=50.0):
            return {"dsmUrl": "http://x/dsm", "maskUrl": "http://x/mask"}

    def fetch(url, key):
        return dsm_b if url.endswith("dsm") else mask_b

    model = build_model_light(LAT0, LON0, "k", client=FakeClient(), fetch=fetch)
    ll = model.line_lengths()
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4
    assert ll.get("valley", {"count": 0})["count"] == 0     # a hip has no valleys
    assert ll["eave"]["length_ft"] == pytest.approx(128.0, rel=0.2)
    assert ll["hip"]["length_ft"] == pytest.approx(72.0, rel=0.25)


def test_spurious_plane_is_pruned():
    # An extra bogus segment (a noise plane Solar shouldn't have) must not create
    # phantom facets/valleys: pruning drops planes that own too little roof.
    facets = hip_roof(40, 24, 6)
    dsm_b, mask_b, segs = _synth(facets)
    segs = segs + [{"pitchDegrees": 38.0, "azimuthDegrees": 47.0,
                    "center": dict(segs[0]["center"]),
                    "planeHeightAtCenterMeters": segs[0]["planeHeightAtCenterMeters"] + 1.5}]
    payload = {"solarPotential": {"roofSegmentStats": segs}}

    class FakeClient:
        def building_insights(self, lat, lng):
            return payload

        def data_layers(self, lat, lng, radius_m=50.0):
            return {"dsmUrl": "http://x/dsm", "maskUrl": "http://x/mask"}

    def fetch(url, key):
        return dsm_b if url.endswith("dsm") else mask_b

    model = build_model_light(LAT0, LON0, "k", client=FakeClient(), fetch=fetch)
    assert len(model.facets) == 4          # spurious plane pruned
    ll = model.line_lengths()
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4
    assert "valley" not in ll and "rake" not in ll   # a hip has neither


def test_light_hip_roundtrip():
    facets = hip_roof(40, 24, 6)
    dsm_b, mask_b, segs = _synth(facets)
    payload = {"solarPotential": {"roofSegmentStats": segs}}

    class FakeClient:
        def building_insights(self, lat, lng):
            return payload

        def data_layers(self, lat, lng, radius_m=50.0):
            return {"dsmUrl": "http://x/dsm", "maskUrl": "http://x/mask"}

    def fetch(url, key):
        return dsm_b if url.endswith("dsm") else mask_b

    model = build_model_light(LAT0, LON0, "k", client=FakeClient(), fetch=fetch)
    ll = model.line_lengths()
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4
    assert ll["eave"]["count"] == 4
    # recovered facets are real polygons (not the 4-corner bbox rectangles)
    assert len(model.facets) == 4
