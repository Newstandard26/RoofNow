"""
synth.py — rasterize known 3D facets into a synthetic DSM + mask + plane priors.

Lets us test recover.py end-to-end with NO live API: build a DSM from a roof whose
true measurements we know, recover polygons from it, and check we get the roof back.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from roofwall.cv.recover import RasterTransform, abc_from_normal, plane_z
from roofwall.measurement.edges import EdgeFacet as Facet

Vec = Tuple[float, float, float]


def _point_in_poly2d(x: float, y: float, verts: List[Vec]) -> bool:
    inside = False
    n = len(verts)
    j = n - 1
    for i in range(n):
        xi, yi = verts[i][0], verts[i][1]
        xj, yj = verts[j][0], verts[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def rasterize(facets: List[Facet], res: float = 0.5, pad_ft: float = 2.0
              ) -> Tuple[np.ndarray, np.ndarray, RasterTransform, List[Dict]]:
    """Return (dsm, mask, transform, priors) for a list of edges.EdgeFacet."""
    xs = [v[0] for f in facets for v in f.verts]
    ys = [v[1] for f in facets for v in f.verts]
    xmin, xmax = min(xs) - pad_ft, max(xs) + pad_ft
    ymin, ymax = min(ys) - pad_ft, max(ys) + pad_ft
    ncols = int(np.ceil((xmax - xmin) / res)) + 1
    nrows = int(np.ceil((ymax - ymin) / res)) + 1
    transform = RasterTransform(x0=xmin, y0=ymin, res=res, nrows=nrows)

    planes = [abc_from_normal(f.normal, f.verts[0]) for f in facets]

    dsm = np.zeros((nrows, ncols), dtype=float)
    mask = np.zeros((nrows, ncols), dtype=np.uint8)

    for row in range(nrows):
        for col in range(ncols):
            x, y = transform.colrow_to_world(col, row)
            best_i, best_z = -1, -1e18
            for i, f in enumerate(facets):
                if _point_in_poly2d(x, y, f.verts):
                    z = plane_z(planes[i], x, y)
                    if z > best_z:  # topmost surface wins on any overlap
                        best_z, best_i = z, i
            if best_i >= 0:
                dsm[row, col] = best_z
                mask[row, col] = 1

    priors = [{"id": f.id, "abc": planes[i]} for i, f in enumerate(facets)]
    return dsm, mask, transform, priors
