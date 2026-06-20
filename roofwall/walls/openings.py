"""Window/door opening measurement via oblique-photo rectification (Phase 2).

Rectify a façade photo with a homography (4 façade corners -> rectangle,
``cv2.findHomography`` + ``cv2.warpPerspective``), measure window/door
rectangles in real units, and subtract from gross wall area. A façade
segmentation model can auto-detect openings later (Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Opening:
    """A measured façade opening, in feet."""

    width_ft: float
    height_ft: float
    kind: str = "window"  # "window" | "door"

    @property
    def area_sqft(self) -> float:
        return self.width_ft * self.height_ft


def rectify_and_measure(image_path: str, facade_corners, real_width_ft: float):
    """Rectify a façade and return measured :class:`Opening`s. (Phase 2.)"""
    raise NotImplementedError(
        "Opening rectification is Phase 2 (opencv homography)."
    )
