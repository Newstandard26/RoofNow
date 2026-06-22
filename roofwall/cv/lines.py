"""Accurate roof line lengths from fitted planes + a labelled raster.

The trace-and-snap approach measured each facet's pixel boundary independently;
when recovered facets don't share edges exactly, every boundary segment reads as
an unshared "rake" (the 50-rakes-on-a-hip-roof bug). This module instead derives
lines from plane *geometry*, the way commercial measurers do:

  * interior edges (ridge / hip / valley) = intersection line of two adjacent
    fitted planes, clipped to the pixels their regions share;
  * eave / rake = the roof's outer outline, each segment classified by whether
    the facet it bounds is level (eave) or sloped (rake) along it.

Pure numpy + contourpy, so it stays in the lightweight Vercel stack.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np
from contourpy import contour_generator

from roofwall.cv.light import _dp
from roofwall.cv.recover import RasterTransform, plane_z

_FLAT_SLOPE = 0.09          # |dz/dxy| below this is "level" (~5 deg)
_FLAT_VALLEY = 0.05         # a level interior edge is a ridge unless concave


def _world_to_colrow(t: RasterTransform, x: float, y: float) -> Tuple[float, float]:
    col = (x - t.x0) / t.res
    row = (t.nrows - 1) - (y - t.y0) / t.res
    return col, row


def _label_at(labels: np.ndarray, t: RasterTransform, x: float, y: float) -> int:
    col, row = _world_to_colrow(t, x, y)
    c, r = int(round(col)), int(round(row))
    if 0 <= r < labels.shape[0] and 0 <= c < labels.shape[1]:
        return int(labels[r, c])
    return -1


def _interior_borders(labels: np.ndarray) -> Dict[Tuple[int, int], List[Tuple[float, float]]]:
    """Map each adjacent facet pair -> list of (col, row) border-crossing points."""
    out: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    L = labels
    # horizontal crossings between (r, c) and (r, c+1)
    left, right = L[:, :-1], L[:, 1:]
    m = (left != right) & (left >= 0) & (right >= 0)
    rr, cc = np.nonzero(m)
    for r, c in zip(rr.tolist(), cc.tolist()):
        key = (min(int(left[r, c]), int(right[r, c])),
               max(int(left[r, c]), int(right[r, c])))
        out.setdefault(key, []).append((c + 0.5, float(r)))
    # vertical crossings between (r, c) and (r+1, c)
    top, bot = L[:-1, :], L[1:, :]
    m = (top != bot) & (top >= 0) & (bot >= 0)
    rr, cc = np.nonzero(m)
    for r, c in zip(rr.tolist(), cc.tolist()):
        key = (min(int(top[r, c]), int(bot[r, c])),
               max(int(top[r, c]), int(bot[r, c])))
        out.setdefault(key, []).append((float(c), r + 0.5))
    return out


def _classify_interior(i_idx, j_idx, planes, labels, transform, pts_world):
    """Return (kind, length_ft) for the shared edge of facets i_idx, j_idx."""
    pi, pj = planes[i_idx], planes[j_idx]
    ai, bi, ci = pi
    aj, bj, cj = pj
    A, B = ai - aj, bi - bj          # intersection line normal in xy
    nrm = math.hypot(A, B)
    if nrm < 1e-9:
        return None                  # parallel planes — no edge
    dhx, dhy = -B / nrm, A / nrm     # unit direction along the line
    xs = np.array([p[0] for p in pts_world])
    ys = np.array([p[1] for p in pts_world])
    ts = xs * dhx + ys * dhy
    length_xy = float(ts.max() - ts.min())
    if length_xy <= 0:
        return None
    slope_along = ai * dhx + bi * dhy
    length_3d = length_xy * math.hypot(1.0, slope_along)

    # Convex (ridge/hip) vs concave (valley): probe just off the edge on each
    # side. The roof is the *lower* envelope of the two planes at a ridge/hip,
    # the *upper* envelope at a valley. So in a region, the edge is convex iff
    # that region's own plane sits below the neighbour's there.
    nx, ny = A / nrm, B / nrm
    mx, my = float(xs.mean()), float(ys.mean())
    step = transform.res * 2.0
    votes = 0
    for s in (1.0, -1.0):
        px, py = mx + s * step * nx, my + s * step * ny
        lab = _label_at(labels, transform, px, py)
        if lab == i_idx:
            own, other = pi, pj
        elif lab == j_idx:
            own, other = pj, pi
        else:
            continue
        votes += 1 if plane_z(own, px, py) < plane_z(other, px, py) else -1
    convex = votes >= 0

    level = abs(slope_along) < _FLAT_SLOPE
    if convex:
        kind = "ridge" if level else "hip"
    else:
        kind = "valley"
    return kind, length_3d


def _outline_segments(labels, transform, simplify_ft):
    region = (labels >= 0).astype(float)
    if region.sum() == 0:
        return []
    z = np.pad(region, 1)
    lines = contour_generator(z=z).lines(0.5)
    if not lines:
        return []
    best = max(lines, key=len)
    pts = [transform.colrow_to_world(col - 1, row - 1) for col, row in best]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return []
    eps = max(simplify_ft / max(transform.res, 1e-6), 0.5)
    simp = _dp(pts + [pts[0]], eps)
    segs = [(simp[k], simp[k + 1]) for k in range(len(simp) - 1)]
    return segs


def _facet_at(px, py, nx, ny, labels, transform, nplanes):
    """Facet just inside the outline at (px, py); probe both sides of normal."""
    for s in (1.0, -1.0):
        lab = _label_at(labels, transform, px + s * transform.res * 2 * nx,
                        py + s * transform.res * 2 * ny)
        if 0 <= lab < nplanes:
            return lab
    return -1


def _split_outline_segment(p0, p1, labels, transform, planes):
    """Split one outline segment into runs of constant bounding facet.

    A gable end is a single straight line top-down but is two rakes on two
    facets; splitting where the facet underneath changes recovers both (and
    their correct per-facet slopes). Yields (q0, q1, facet_index).
    """
    ux, uy = p1[0] - p0[0], p1[1] - p0[1]
    seglen = math.hypot(ux, uy)
    if seglen == 0:
        return
    nx, ny = -uy / seglen, ux / seglen
    n = max(1, int(round(seglen / max(transform.res, 0.5))))
    facs = []
    for k in range(n):
        t = (k + 0.5) / n
        facs.append(_facet_at(p0[0] + ux * t, p0[1] + uy * t, nx, ny,
                              labels, transform, len(planes)))
    start = 0
    for k in range(1, n + 1):
        if k == n or facs[k] != facs[start]:
            q0 = (p0[0] + ux * start / n, p0[1] + uy * start / n)
            q1 = (p0[0] + ux * k / n, p0[1] + uy * k / n)
            yield q0, q1, facs[start]
            start = k


def measure_lines(labels, planes, transform, mask=None, *,
                  min_shared_px: int = 6, simplify_ft: float = 2.0,
                  min_edge_ft: float = 2.0) -> Dict[str, dict]:
    """Aggregate roof line lengths -> {type: {count, length_ft}} (+ drip_edge)."""
    acc: Dict[str, List[float]] = {k: [] for k in
                                   ("ridge", "hip", "valley", "eave", "rake")}

    borders = _interior_borders(np.asarray(labels))
    for (i, j), px_pts in borders.items():
        if len(px_pts) < min_shared_px or i >= len(planes) or j >= len(planes):
            continue
        world = [transform.colrow_to_world(c, r) for c, r in px_pts]
        res = _classify_interior(i, j, planes, labels, transform, world)
        if res and res[1] >= min_edge_ft:
            acc[res[0]].append(res[1])

    for p0, p1 in _outline_segments(labels, transform, simplify_ft):
        for q0, q1, fi in _split_outline_segment(p0, p1, labels, transform, planes):
            if fi < 0:
                continue
            ux, uy = q1[0] - q0[0], q1[1] - q0[1]
            seg_xy = math.hypot(ux, uy)
            if seg_xy < min_edge_ft:
                continue
            a, b, _c = planes[fi]
            slope_along = (a * ux + b * uy) / seg_xy
            length_3d = seg_xy * math.hypot(1.0, slope_along)
            acc["eave" if abs(slope_along) < _FLAT_SLOPE else "rake"].append(length_3d)

    out: Dict[str, dict] = {}
    for kind, lens in acc.items():
        if lens:
            out[kind] = {"count": len(lens), "length_ft": round(sum(lens), 1)}
    drip = sum(sum(acc[k]) for k in ("eave", "rake"))
    if drip > 0:
        out["drip_edge"] = {"length_ft": round(drip, 1), "note": "eaves + rakes"}
    return out
