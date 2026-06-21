"""
CRS round-trip test for geo.py — proves the meters/Mercator -> ground-feet conversion.

Synthesizes a real EPSG:3857 (Web Mercator) DSM GeoTIFF of a known hip roof at
Machesney Park's latitude, then runs geotiff_to_local + recover and checks:
  - recovered ground resolution ~ 0.5 ft  (a naive "treat 3857 units as feet"
    implementation would yield ~0.67 ft here — a 35% scale error)
  - roof topology + line lengths come back correct through the full real-data path.
"""
import math
import os
import tempfile

import pytest

# geo/recover need the geospatial stack; skip cleanly if any of it is absent.
pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
pytest.importorskip("skimage")
pytest.importorskip("shapely")

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from pyproj import Transformer  # noqa: E402

from roofwall.cv.geo import M2FT, R_EARTH, geotiff_to_local, priors_from_solar  # noqa: E402
from roofwall.cv.recover import abc_from_normal, plane_z, recover  # noqa: E402
from roofwall.cv.synth import _point_in_poly2d  # noqa: E402
from roofwall.measurement.edges import classify_edges, hip_roof, summarize  # noqa: E402
from roofwall.measurement.snapping import to_roof_edges  # noqa: E402

LAT0, LON0 = 42.3483, -89.0421  # Machesney Park, IL (your benchmark property)
GROUND_RES_FT = 0.5


def _local_ft_to_lonlat(x_ft, y_ft):
    coslat = math.cos(math.radians(LAT0))
    lon = LON0 + math.degrees((x_ft / M2FT) / (R_EARTH * coslat))
    lat = LAT0 + math.degrees((y_ft / M2FT) / R_EARTH)
    return lon, lat


def _write_synthetic_mercator_geotiff(facets, path, mask_path=None):
    """Render a hip roof into a real EPSG:3857 DSM GeoTIFF (heights in meters).
    If ``mask_path`` is given, also write the building mask on the same grid."""
    to_merc = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    planes = [abc_from_normal(f.normal, f.verts[0]) for f in facets]

    # footprint extent in 3857
    mxs, mys = [], []
    for f in facets:
        for v in f.verts:
            lon, lat = _local_ft_to_lonlat(v[0], v[1])
            mx, my = to_merc.transform(lon, lat)
            mxs.append(mx); mys.append(my)
    pad = 2.0  # meters
    xmin, xmax = min(mxs) - pad, max(mxs) + pad
    ymin, ymax = min(mys) - pad, max(mys) + pad

    # 0.5 ft ground -> 3857 units (inflated by sec(lat)); this is the distortion under test
    px = (GROUND_RES_FT / M2FT) / math.cos(math.radians(LAT0))
    ncols = int(math.ceil((xmax - xmin) / px)) + 1
    nrows = int(math.ceil((ymax - ymin) / px)) + 1
    transform = from_origin(xmin, ymax, px, px)
    to_geo = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    to_local = geo_local_factory()

    dsm = np.zeros((nrows, ncols), dtype=np.float32)
    mask = np.zeros((nrows, ncols), dtype=np.uint8)
    for row in range(nrows):
        for col in range(ncols):
            mx = xmin + (col + 0.5) * px
            my = ymax - (row + 0.5) * px
            lon, lat = to_geo.transform(mx, my)
            x_ft, y_ft = to_local(lon, lat)
            best_i, best_z = -1, -1e18
            for i, f in enumerate(facets):
                if _point_in_poly2d(x_ft, y_ft, f.verts):
                    z = plane_z(planes[i], x_ft, y_ft)
                    if z > best_z:
                        best_z, best_i = z, i
            if best_i >= 0:
                dsm[row, col] = best_z / M2FT  # store meters
                mask[row, col] = 1

    with rasterio.open(path, "w", driver="GTiff", height=nrows, width=ncols,
                       count=1, dtype="float32", crs="EPSG:3857", transform=transform) as dst:
        dst.write(dsm, 1)
    if mask_path is not None:
        with rasterio.open(mask_path, "w", driver="GTiff", height=nrows, width=ncols,
                           count=1, dtype="uint8", crs="EPSG:3857", transform=transform) as dst:
            dst.write(mask, 1)
    return mask


def geo_local_factory():
    coslat = math.cos(math.radians(LAT0))

    def to_local(lon, lat):
        e = math.radians(lon - LON0) * coslat * R_EARTH
        n = math.radians(lat - LAT0) * R_EARTH
        return (e * M2FT, n * M2FT)
    return to_local


def _segments_from_facets(facets):
    segs = []
    for i, f in enumerate(facets):
        nx, ny, nz = f.normal
        pitch = math.degrees(math.acos(min(1.0, abs(nz))))
        az = (math.degrees(math.atan2(nx, ny)) + 360) % 360
        cx, cy, cz = f.cen
        lon, lat = _local_ft_to_lonlat(cx, cy)
        segs.append({"id": f.id, "pitch_degrees": pitch, "azimuth_degrees": az,
                     "center": {"latitude": lat, "longitude": lon},
                     "plane_height_m": cz / M2FT})
    return segs


def test_mercator_scale_is_corrected():
    facets = hip_roof(40, 24, 6)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "dsm.tif")
        _write_synthetic_mercator_geotiff(facets, path)
        _arr, _tf, _l2l, meta = geotiff_to_local(path)
    # ground resolution must come back ~0.5 ft, NOT ~0.67 (the sec(lat) trap)
    assert abs(meta["res_ft"] - GROUND_RES_FT) / GROUND_RES_FT < 0.03, meta
    assert meta["rotation_warn"] is False
    naive = (GROUND_RES_FT / math.cos(math.radians(LAT0)))  # if 3857 units were taken as-is
    assert abs(meta["res_ft"] - naive) > 0.10  # proves we did NOT make the naive error


def test_full_real_data_path_roundtrip():
    facets = hip_roof(40, 24, 6)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "dsm.tif")
        mask = _write_synthetic_mercator_geotiff(facets, path)
        dsm_ft, transform, lonlat_to_local, meta = geotiff_to_local(path)
        priors = priors_from_solar(_segments_from_facets(facets), lonlat_to_local)
        rec = recover(dsm_ft, mask, transform, priors)
    s = summarize(classify_edges(to_roof_edges(rec)))
    assert int(s["ridge"]["count"]) == 1
    assert int(s["hip"]["count"]) == 4
    assert int(s["eave"]["count"]) == 4
    assert "valley" not in s
    assert abs(s["ridge"]["length"] - 16.0) / 16.0 < 0.20
    assert abs(s["hip"]["length"] - 72.0) / 72.0 < 0.15
    assert abs(s["eave"]["length"] - 128.0) / 128.0 < 0.10


def test_geotiffs_to_building_model():
    # DSM + mask GeoTIFFs + Solar segments -> BuildingModel (the production bridge).
    from roofwall.cv.solar_dsm import build_model_from_geotiffs
    from roofwall.model import Origin

    facets = hip_roof(40, 24, 6)
    with tempfile.TemporaryDirectory() as d:
        dsm_path = os.path.join(d, "dsm.tif")
        mask_path = os.path.join(d, "mask.tif")
        _write_synthetic_mercator_geotiff(facets, dsm_path, mask_path=mask_path)
        segments = _segments_from_facets(facets)
        model = build_model_from_geotiffs(dsm_path, mask_path, segments, Origin(LAT0, LON0))
    assert model.source == "solar-dsm"
    ll = model.line_lengths()
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4
    assert ll["eave"]["count"] == 4
