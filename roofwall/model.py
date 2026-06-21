"""BuildingModel — the output contract of facet boundary recovery.

This is the only thing the rest of the app depends on. A ``BuildingModel``
carries real per-facet 3D polygons in a local metric (ENU, feet) frame; its
``facets`` feed straight into the edge classifier to produce true ridge / hip
/ valley / eave / rake line lengths.

Mirrors the TypeScript contract:

    interface BuildingModel {
      facets: { id: string; verts: [number, number, number][] }[];
      origin: { lat: number; lng: number };
      source: "solar-dsm" | "lidar";
      notes?: string;
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from roofwall.measurement.edges import EdgeFacet, Vec, line_lengths_dict, make_facet
from roofwall.measurement.snapping import weld

# Allowed provenance. "synthetic" is used by the M1 plumbing fixture.
SOURCES = ("solar-dsm", "lidar", "synthetic")


@dataclass
class ModelFacet:
    id: str
    verts: List[Vec]


@dataclass
class Origin:
    lat: float
    lng: float


@dataclass
class BuildingModel:
    facets: List[ModelFacet]
    origin: Origin
    source: str
    notes: Optional[str] = None

    def to_edge_facets(self) -> List[EdgeFacet]:
        return [make_facet(f.id, f.verts, source=self.source) for f in self.facets]

    def welded(self, **tol: float) -> List[EdgeFacet]:
        """Edge facets after shared-edge snapping (ready for classification)."""
        return weld(self.to_edge_facets(), **tol)

    def line_lengths(self, *, snap: bool = True) -> dict[str, Any]:
        """Length Diagram (ridge/hip/valley/eave/rake). Snaps edges first."""
        facets = self.welded() if snap else self.to_edge_facets()
        return line_lengths_dict(facets)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the BuildingModel contract shape."""
        return {
            "facets": [
                {"id": f.id, "verts": [list(v) for v in f.verts]}
                for f in self.facets
            ],
            "origin": {"lat": self.origin.lat, "lng": self.origin.lng},
            "source": self.source,
            "notes": self.notes,
        }

    @classmethod
    def from_edge_facets(
        cls,
        facets: List[EdgeFacet],
        origin: Origin,
        source: str,
        notes: Optional[str] = None,
    ) -> "BuildingModel":
        return cls(
            facets=[ModelFacet(f.id, list(f.verts)) for f in facets],
            origin=origin,
            source=source,
            notes=notes,
        )
