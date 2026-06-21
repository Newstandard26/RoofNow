"""
geo.py — turn a Solar Data-Layers GeoTIFF (DSM) into the local-feet frame recover.py needs.

This solves the one real wrinkle in wiring recovery to live data: coordinate reference
systems. Solar DSM rasters are NOT in feet — they're in a projected CRS (commonly Web
Mercator / EPSG:3857), whose units are distorted by latitude. Naively treating those
units as ground distance overstates everything by sec(latitude) — about +35% at lat 42°
(Machesney Park). geotiff_to_local() removes that distortion and returns true ground feet.

Returns:
  arr               : the raster as a numpy array (DSM heights in METERS, untouched)
  transform         : recover.RasterTransform in local FEET (x=East, y=North, row0=top)
  lonlat_to_local   : fn(lon, lat) -> (x_ft, y_ft) so Solar segment centers land in the
                      SAME frame as the raster (essential — priors must match the DSM)
  meta              : {res_ft, col_axis_deg, rotation_warn, lon0, lat0, ...}

Deps: numpy, rasterio, pyproj.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Tuple

import numpy as np
import rasterio
from pyproj import Transformer

from roofwall.cv.recover import RasterTransform, plane_from_solar_segment

M2FT = 3.28084
R_EARTH = 6378137.0  # WGS84 mean radius, meters


def _lonlat_to_local_factory(lon0: float, lat0: float) -> Callable[[float, float], Tuple[float, float]]:
    """Equirectangular local ENU (feet) about (lon0, lat0). mm-accurate over one building."""
    coslat = math.cos(math.radians(lat0))

    def to_local(lon: float, lat: float) -> Tuple[float, float]:
        e_m = math.radians(lon - lon0) * coslat * R_EARTH
        n_m = math.radians(lat - lat0) * R_EARTH
        return (e_m * M2FT, n_m * M2FT)

    return to_local


def geotiff_to_local(path_or_dataset, band: int = 1, ref_lonlat=None, to_feet: bool = True):
    """to_feet: multiply pixel values by 3.28084 (use for a DSM in meters; set False
    when reading a building mask / categorical raster)."""
    ds = rasterio.open(path_or_dataset) if isinstance(path_or_dataset, str) else path_or_dataset
    arr = ds.read(band).astype(float)
    if to_feet:
        arr = arr * M2FT  # DSM heights meters -> feet, to match feet-based planes
    nrows, ncols = arr.shape
    A = ds.transform
    to_geo = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)

    def center_lonlat(col: float, row: float) -> Tuple[float, float]:
        x, y = A * (col + 0.5, row + 0.5)
        lon, lat = to_geo.transform(x, y)
        return lon, lat

    lon0, lat0 = ref_lonlat if ref_lonlat is not None else center_lonlat(0, 0)
    lonlat_to_local = _lonlat_to_local_factory(lon0, lat0)

    def loc(col: float, row: float) -> Tuple[float, float]:
        return lonlat_to_local(*center_lonlat(col, row))

    p00, p10, p01 = loc(0, 0), loc(1, 0), loc(0, 1)
    res_col = math.hypot(p10[0] - p00[0], p10[1] - p00[1])
    res_row = math.hypot(p01[0] - p00[0], p01[1] - p00[1])
    res = 0.5 * (res_col + res_row)

    # column axis should point +East (0deg), row axis -North; warn if the grid is rotated
    col_axis_deg = math.degrees(math.atan2(p10[1] - p00[1], p10[0] - p00[0]))
    rot = min(abs(col_axis_deg), abs(col_axis_deg - 360), abs(col_axis_deg + 360))

    x_bl, y_bl = loc(0, nrows - 1)  # bottom-left pixel center = (x0, y0)
    transform = RasterTransform(x0=x_bl, y0=y_bl, res=res, nrows=nrows)

    meta: Dict = {
        "res_ft": res,
        "res_col_ft": res_col,
        "res_row_ft": res_row,
        "col_axis_deg": col_axis_deg,
        "rotation_warn": rot > 1.0,
        "lon0": lon0,
        "lat0": lat0,
        "src_crs": str(ds.crs),
        "shape": (nrows, ncols),
    }
    return arr, transform, lonlat_to_local, meta


def priors_from_solar(segments: List[Dict],
                      lonlat_to_local: Callable[[float, float], Tuple[float, float]]
                      ) -> List[Dict]:
    """
    Build recover() priors from Solar roofSegmentStats, in the raster's local frame.
    Each segment dict needs: id, pitch_degrees, azimuth_degrees,
                             center {latitude, longitude}, plane_height_m.
    """
    priors = []
    for s in segments:
        x, y = lonlat_to_local(s["center"]["longitude"], s["center"]["latitude"])
        z = s["plane_height_m"] * M2FT
        abc = plane_from_solar_segment(s["pitch_degrees"], s["azimuth_degrees"], (x, y, z))
        priors.append({"id": str(s["id"]), "abc": abc})
    return priors
