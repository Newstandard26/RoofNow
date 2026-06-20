"""Window/door opening measurement via oblique-photo rectification (Phase 2).

Map a façade photo to real-world coordinates with a homography (4 façade
corners -> a rectangle of known real width/height), then measure window and
door rectangles in feet and subtract them from the gross wall area.

The homography solve and point mapping are done in numpy here so they are
unit-testable without OpenCV. ``cv2.warpPerspective`` is only needed to warp
the actual image *pixels* (e.g. to display a rectified façade) and lives
behind the optional ``walls-io`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

Corners = Sequence[Sequence[float]]  # 4 points, ordered TL, TR, BR, BL


@dataclass(frozen=True)
class Opening:
    """A measured façade opening, in feet."""

    width_ft: float
    height_ft: float
    kind: str = "window"  # "window" | "door"

    @property
    def area_sqft(self) -> float:
        return self.width_ft * self.height_ft


def compute_homography(src: Corners, dst: Corners) -> np.ndarray:
    """Homography mapping ``src`` points to ``dst`` points (Direct Linear
    Transform, 4+ correspondences). Returns a 3x3 matrix, normalized so
    ``H[2,2] == 1``.
    """
    s = np.asarray(src, dtype=float)
    d = np.asarray(dst, dtype=float)
    if s.shape != d.shape or s.shape[0] < 4 or s.shape[1] != 2:
        raise ValueError("src/dst must be matching (>=4, 2) point sets")

    rows = []
    for (x, y), (u, v) in zip(s, d):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    a = np.asarray(rows, dtype=float)
    # Solution is the right singular vector of the smallest singular value.
    _, _, vh = np.linalg.svd(a)
    h = vh[-1].reshape(3, 3)
    if abs(h[2, 2]) < 1e-12:
        raise ValueError("degenerate homography")
    return h / h[2, 2]


def apply_homography(h: np.ndarray, point: Sequence[float]) -> tuple[float, float]:
    """Map a single point through homography ``h``."""
    x, y = float(point[0]), float(point[1])
    denom = h[2, 0] * x + h[2, 1] * y + h[2, 2]
    u = (h[0, 0] * x + h[0, 1] * y + h[0, 2]) / denom
    v = (h[1, 0] * x + h[1, 1] * y + h[1, 2]) / denom
    return float(u), float(v)


def facade_homography(
    facade_corners: Corners, real_width_ft: float, real_height_ft: float
) -> np.ndarray:
    """Homography from façade pixel corners (TL,TR,BR,BL) to real feet."""
    if real_width_ft <= 0 or real_height_ft <= 0:
        raise ValueError("real façade dimensions must be positive")
    dst = [
        (0.0, 0.0),
        (real_width_ft, 0.0),
        (real_width_ft, real_height_ft),
        (0.0, real_height_ft),
    ]
    return compute_homography(facade_corners, dst)


def measure_opening(
    homography: np.ndarray, pixel_corners: Corners, *, kind: str = "window"
) -> Opening:
    """Measure an opening (given by 4 pixel corners) in real feet."""
    real = [apply_homography(homography, p) for p in pixel_corners]
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = real
    top = abs(trx - tlx)
    bottom = abs(brx - blx)
    left = abs(bly - tly)
    right = abs(bry - try_)
    width = (top + bottom) / 2.0
    height = (left + right) / 2.0
    return Opening(width_ft=width, height_ft=height, kind=kind)


def total_opening_area(
    homography: np.ndarray, openings_pixel_corners: Sequence[Corners]
) -> float:
    """Sum of measured opening areas (sqft) for a façade."""
    return sum(
        measure_opening(homography, c).area_sqft for c in openings_pixel_corners
    )


def rectify_image(image_path: str, homography: np.ndarray, out_size):
    """Warp façade pixels to a rectified image. (Needs the 'walls-io' extra.)"""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "Image warping needs the 'walls-io' extra: pip install roofwall[walls-io]"
        ) from exc
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(image_path)
    return cv2.warpPerspective(img, homography, tuple(out_size))
