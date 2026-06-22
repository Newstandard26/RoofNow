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


def _synth(facets):
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
