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
_RAKE_SLOPE = 0.25          # outline: only call it a rake if the facet really
                            # climbs along the edge (~14 deg). Below this it's an
                            # eave whose facet plane is merely slightly skew-fit;
                            # a true gable rake runs at the full pitch (~0.5).


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


def _convex_at(mx, my, i_idx, j_idx, pi, pj, nx, ny, labels, transform):
    """True if the shared edge is convex (ridge/hip) near (mx, my).

    Steps off the edge along the planes' gradient-difference normal and asks, on
    each facet's own side, whether that facet's plane sits *below* the other —
    the signature of a peak (ridge/hip) rather than a trough (valley). Sampling
    at several distances and voting makes the side lookup robust to the ragged
    1-2 px boundary smoothing leaves (a single near-edge mis-read used to flip a
    whole hip to a valley).
    """
    res = transform.res
    votes = 0
    for d in (2.0, 3.0, 4.0, 5.0):
        for s in (1.0, -1.0):
            px, py = mx + s * d * res * nx, my + s * d * res * ny
            lab = _label_at(labels, transform, px, py)
            if lab == i_idx:
                own, other = pi, pj
            elif lab == j_idx:
                own, other = pj, pi
            else:
                continue
            votes += 1 if plane_z(own, px, py) < plane_z(other, px, py) else -1
    return votes >= 0


def _interior_segments(i_idx, j_idx, planes, labels, transform, pts_world, *,
                       gap_ft=2.5, min_len_ft=4.0, max_perp_ft=4.0):
    """Shared edge(s) of facets i,j -> list of (kind, length_ft).

    Projects the shared-border pixels onto the planes' intersection line, then
    splits them into contiguous runs (breaking where there's a gap along the
    line) so multiple separate borders aren't fused into one giant span and the
    length isn't inflated across gaps. Runs that are too short, or too spread
    perpendicular to the line (a 2-D interleave patch, not a clean edge), are
    dropped.
    """
    pi, pj = planes[i_idx], planes[j_idx]
    ai, bi, _ci = pi
    A, B = ai - pj[0], bi - pj[1]
    nrm = math.hypot(A, B)
    if nrm < 1e-9:
        return []
    dhx, dhy = -B / nrm, A / nrm     # along the line
    nx, ny = A / nrm, B / nrm        # perpendicular
    xs = np.array([p[0] for p in pts_world])
    ys = np.array([p[1] for p in pts_world])
    t = xs * dhx + ys * dhy
    u = xs * nx + ys * ny
    order = np.argsort(t)
    t, u, xs, ys = t[order], u[order], xs[order], ys[order]
    slope_along = ai * dhx + bi * dhy
    level = abs(slope_along) < _FLAT_SLOPE
    factor = math.hypot(1.0, slope_along)

    segs = []
    start = 0
    n = len(t)
    for k in range(1, n + 1):
        if k == n or (t[k] - t[k - 1]) > gap_ft:
            run = slice(start, k)
            start = k
            length_xy = float(t[run.stop - 1] - t[run.start]) if run.stop > run.start else 0.0
            if length_xy < min_len_ft:
                continue
            perp = float(u[run].max() - u[run].min())
            if perp > max_perp_ft and perp > 0.6 * length_xy:
                continue                                 # 2-D patch, not an edge
            convex = _convex_at(float(xs[run].mean()), float(ys[run].mean()),
                                i_idx, j_idx, pi, pj, nx, ny, labels, transform)
            kind = ("ridge" if level else "hip") if convex else "valley"
            segs.append((kind, length_xy * factor))
    return segs


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


def _outline_dsm_slope(q0, q1, labels, transform, dsm):
    """Actual along-edge slope (dz/d_along, ft/ft) read from the DSM.

    The facet-plane slope is unreliable on the outline: a short perimeter run at
    a corner gets attributed to a steep neighbour (e.g. a N-S segment lands on a
    North-facing facet and reads as "climbing"), counting a level eave as a rake.
    The DSM doesn't care about that attribution — we sample the real surface just
    *inside* the roof and parallel to the edge, so a level eave reads ~0 and only
    a true gable rake (the surface genuinely climbs along the edge) reads ~pitch.
    Sampling tangentially + inward avoids the perpendicular cliff at the eave.
    Returns None (caller falls back to the plane) if too few on-roof samples.
    """
    if dsm is None:
        return None
    ux, uy = q1[0] - q0[0], q1[1] - q0[1]
    L = math.hypot(ux, uy)
    if L == 0:
        return None
    nx, ny = -uy / L, ux / L
    res = transform.res

    def height(x, y):
        col, row = _world_to_colrow(transform, x, y)
        c, r = int(round(col)), int(round(row))
        if 0 <= r < dsm.shape[0] and 0 <= c < dsm.shape[1] and labels[r, c] >= 0:
            return float(dsm[r, c])
        return None

    mx, my = q0[0] + ux * 0.5, q0[1] + uy * 0.5
    plus = sum(height(mx + d * res * nx, my + d * res * ny) is not None for d in (2., 3., 4.))
    minus = sum(height(mx - d * res * nx, my - d * res * ny) is not None for d in (2., 3., 4.))
    s_in = 1.0 if plus >= minus else -1.0
    off = 2.5 * res

    ts, hs = [], []
    n = max(4, int(L / max(res, 1e-6)))
    for k in range(n + 1):
        t = k / n
        if t < 0.15 or t > 0.85:            # skip the corner-contaminated ends
            continue
        h = height(q0[0] + ux * t + s_in * off * nx,
                   q0[1] + uy * t + s_in * off * ny)
        if h is not None:
            ts.append(t * L)
            hs.append(h)
    if len(ts) < 4:
        return None
    ts = np.asarray(ts)
    hs = np.asarray(hs)
    A = np.vstack([ts, np.ones_like(ts)]).T
    return float(np.linalg.lstsq(A, hs, rcond=None)[0][0])


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


def measure_lines(labels, planes, transform, mask=None, *, dsm=None,
                  min_shared_px: int = 6, simplify_ft: float = 1.2,
                  min_edge_ft: float = 2.0, diag: list | None = None) -> Dict[str, dict]:
    """Aggregate roof line lengths -> {type: {count, length_ft}} (+ drip_edge).

    Pass `dsm` (height raster, ft) to classify eave vs rake from the real surface
    slope along each outline edge instead of the bounding facet's plane, which is
    unreliable at corners; falls back to the plane when no DSM is given.

    Pass `diag` (a list) to collect a per-segment breakdown for tuning: each
    entry is a compact dict describing one measured interior or outline segment.
    """
    acc: Dict[str, List[float]] = {k: [] for k in
                                   ("ridge", "hip", "valley", "eave", "rake")}

    borders = _interior_borders(np.asarray(labels))
    for (i, j), px_pts in borders.items():
        if len(px_pts) < min_shared_px or i >= len(planes) or j >= len(planes):
            continue
        world = [transform.colrow_to_world(c, r) for c, r in px_pts]
        for kind, length in _interior_segments(i, j, planes, labels, transform, world):
            acc[kind].append(length)
            if diag is not None:
                diag.append({"e": "int", "ij": [i, j], "k": kind, "L": round(length, 1)})

    for p0, p1 in _outline_segments(labels, transform, simplify_ft):
        for q0, q1, fi in _split_outline_segment(p0, p1, labels, transform, planes):
            if fi < 0:
                continue
            ux, uy = q1[0] - q0[0], q1[1] - q0[1]
            seg_xy = math.hypot(ux, uy)
            if seg_xy < min_edge_ft:
                continue
            a, b, _c = planes[fi]
            dsm_slope = _outline_dsm_slope(q0, q1, labels, transform, dsm)
            slope_along = dsm_slope if dsm_slope is not None else (a * ux + b * uy) / seg_xy
            length_3d = seg_xy * math.hypot(1.0, slope_along)
            kind = "eave" if abs(slope_along) < _RAKE_SLOPE else "rake"
            acc[kind].append(length_3d)
            if diag is not None:
                diag.append({"e": "out", "f": fi, "k": kind,
                             "L": round(length_3d, 1), "s": round(slope_along, 2)})

    out: Dict[str, dict] = {}
    for kind, lens in acc.items():
        if lens:
            out[kind] = {"count": len(lens), "length_ft": round(sum(lens), 1)}
    drip = sum(sum(acc[k]) for k in ("eave", "rake"))
    if drip > 0:
        out["drip_edge"] = {"length_ft": round(drip, 1), "note": "eaves + rakes"}
    return out
