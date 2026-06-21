/**
 * roofEdges.ts — Ridge / hip / valley / eave / rake extraction from a 3D roof model.
 *
 * TypeScript source of the "Total Line Lengths" piece (EagleView Length Diagram).
 * Kept in sync with the Python port roofwall/measurement/edges.py and shares its
 * validated test suite (roofEdges.test.ts mirrors test_edges.py).
 *
 * INPUT: a roof as planar facets, each facet a list of 3D vertices [x, y, z] in feet
 *        (z = height). You get facet polygons from LiDAR plane segmentation, a 3D
 *        reconstruction, or from Google Solar API segments AFTER recovering facet
 *        boundaries from the DSM/building mask.
 *
 * OUTPUT: every edge classified, with true (3D) lengths summed per type.
 *
 * CLASSIFICATION
 *   Boundary edge (1 facet):  level -> EAVE,  sloped -> RAKE
 *   Shared edge   (2 facets):  level -> RIDGE
 *                              sloped -> HIP    (convex fold, sheds water out)
 *                                        VALLEY (concave fold, internal channel)
 *   Hip vs valley: sign of the neighbor facet's centroid vs this facet's plane —
 *   below the plane => convex => hip; above => concave => valley.
 */

export type Vec = [number, number, number];
export type EdgeKind = "eave" | "rake" | "ridge" | "hip" | "valley" | "junction";

// Tolerances (feet)
const SNAP = 0.05; // vertex coincidence for shared-edge matching (~5/8")
const LEVEL_DZ = 0.25; // |Δz| below this => edge is "level"

// ---------- vector helpers ----------
const sub = (a: Vec, b: Vec): Vec => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec, b: Vec): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const scale = (a: Vec, s: number): Vec => [a[0] * s, a[1] * s, a[2] * s];
const normLen = (a: Vec): number => Math.sqrt(dot(a, a));
const dist = (a: Vec, b: Vec): number => normLen(sub(a, b));

/** Robust polygon normal (Newell's method), oriented so z >= 0 (up). */
export function newellNormal(verts: Vec[]): Vec {
  let nx = 0,
    ny = 0,
    nz = 0;
  const n = verts.length;
  for (let i = 0; i < n; i++) {
    const [cx, cy, cz] = verts[i];
    const [dx, dy, dz] = verts[(i + 1) % n];
    nx += (cy - dy) * (cz + dz);
    ny += (cz - dz) * (cx + dx);
    nz += (cx - dx) * (cy + dy);
  }
  const L = normLen([nx, ny, nz]);
  if (L === 0) return [0, 0, 1];
  const nrm: Vec = [nx / L, ny / L, nz / L];
  return nrm[2] >= 0 ? nrm : scale(nrm, -1);
}

export function centroid(verts: Vec[]): Vec {
  const n = verts.length;
  const s: Vec = [0, 0, 0];
  for (const v of verts) {
    s[0] += v[0];
    s[1] += v[1];
    s[2] += v[2];
  }
  return scale(s, 1 / n);
}

const keyOf = (p: Vec): string => {
  const inv = 1 / SNAP;
  return `${Math.round(p[0] * inv)},${Math.round(p[1] * inv)},${Math.round(p[2] * inv)}`;
};

const edgeKey = (a: Vec, b: Vec): string => {
  const ka = keyOf(a);
  const kb = keyOf(b);
  return ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
};

/**
 * A 3D roof facet, lined up with the Python engine's facet representation
 * (roofwall.measurement.engine.FacetMeasurement). The geometric fields
 * (verts/normal/cen) drive edge extraction, while `pitchX12`, `azimuthDeg`
 * and `source` correspond 1:1 to FacetMeasurement.pitch / .azimuth_deg /
 * .source so a geometric facet and a measured facet describe the same surface.
 */
export interface Facet {
  id: string;
  verts: Vec[];
  normal: Vec;
  cen: Vec;
  source: string; // matches FacetMeasurement.source, e.g. "lidar" | "demo"
  azimuthDeg: number; // downslope heading 0=N clockwise (FacetMeasurement.azimuth_deg)
}

/** Downslope/facing heading (0=N, clockwise) — engine azimuth convention. */
export function facetAzimuthDeg(normal: Vec): number {
  const [nx, ny] = normal;
  if (Math.abs(nx) < 1e-12 && Math.abs(ny) < 1e-12) return 0;
  return ((Math.atan2(nx, ny) * 180) / Math.PI + 360) % 360;
}

export function makeFacet(id: string, verts: Vec[], source = "geometry"): Facet {
  const normal = newellNormal(verts);
  return { id, verts, normal, cen: centroid(verts), source, azimuthDeg: facetAzimuthDeg(normal) };
}

/** Roof pitch as rise-in-12 for a facet (matches FacetMeasurement.pitch.x12). */
export function pitchX12(f: Facet): number {
  const nz = Math.min(1, Math.max(1e-9, Math.abs(f.normal[2])));
  const slope = Math.tan(Math.acos(nz)); // rise/run
  return slope * 12;
}

export interface Edge {
  a: Vec;
  b: Vec;
  kind: EdgeKind;
  length: number;
  facets: string[];
}

const signedHeightOffPlane = (point: Vec, planePt: Vec, upNormal: Vec): number =>
  dot(upNormal, sub(point, planePt));

export function classifyEdges(facets: Facet[]): Edge[] {
  const groups = new Map<string, { a: Vec; b: Vec; f: Facet }[]>();
  for (const f of facets) {
    const v = f.verts;
    for (let i = 0; i < v.length; i++) {
      const a = v[i];
      const b = v[(i + 1) % v.length];
      const k = edgeKey(a, b);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)!.push({ a, b, f });
    }
  }

  const edges: Edge[] = [];
  for (const items of groups.values()) {
    const { a, b } = items[0];
    const L = dist(a, b);
    if (L < SNAP) continue;
    const level = Math.abs(a[2] - b[2]) <= LEVEL_DZ;

    // unique facets touching this edge
    const uniq = new Map<string, Facet>();
    for (const it of items) uniq.set(it.f.id, it.f);
    const touching = [...uniq.values()];
    const fids = touching.map((f) => f.id);

    let kind: EdgeKind;
    if (touching.length === 1) {
      kind = level ? "eave" : "rake";
    } else if (touching.length === 2) {
      if (level) {
        kind = "ridge";
      } else {
        const [fa, fb] = touching;
        const s = signedHeightOffPlane(fb.cen, fa.verts[0], fa.normal);
        kind = s < 0 ? "hip" : "valley";
      }
    } else {
      kind = "junction";
    }
    edges.push({ a, b, kind, length: L, facets: fids });
  }
  return edges;
}

export interface TypeSummary {
  count: number;
  length: number;
}

export function summarize(edges: Edge[]): Record<string, TypeSummary> {
  const out: Record<string, TypeSummary> = {};
  for (const e of edges) {
    if (!out[e.kind]) out[e.kind] = { count: 0, length: 0 };
    out[e.kind].count += 1;
    out[e.kind].length += e.length;
  }
  return out;
}

/** Convenience: facets -> summarized line lengths. */
export function lineLengths(facets: Facet[]): Record<string, TypeSummary> {
  return summarize(classifyEdges(facets));
}

// ---------------- demo roof builders (used by tests) ----------------
export function hipRoof(L = 40, W = 24, pitch = 6): Facet[] {
  const run = W / 2;
  const h = (run * pitch) / 12;
  const r1: Vec = [W / 2, W / 2, h];
  const r2: Vec = [L - W / 2, W / 2, h];
  const c00: Vec = [0, 0, 0],
    c10: Vec = [L, 0, 0],
    c11: Vec = [L, W, 0],
    c01: Vec = [0, W, 0];
  return [
    makeFacet("front", [c00, c10, r2, r1]),
    makeFacet("back", [c11, c01, r1, r2]),
    makeFacet("left", [c01, c00, r1]),
    makeFacet("right", [c10, c11, r2]),
  ];
}

export function gableRoof(L = 40, W = 24, pitch = 6): Facet[] {
  const h = ((W / 2) * pitch) / 12;
  const fr: Vec[] = [[0, 0, 0], [L, 0, 0], [L, W / 2, h], [0, W / 2, h]];
  const bk: Vec[] = [[L, W, 0], [0, W, 0], [0, W / 2, h], [L, W / 2, h]];
  return [makeFacet("front", fr), makeFacet("back", bk)];
}

export function valleyPair(): Facet[] {
  const p0: Vec = [0, 0, 0];
  const p1: Vec = [10, 10, 4];
  return [
    makeFacet("A", [p0, p1, [10, 0, 4]]),
    makeFacet("B", [p0, [0, 10, 4], p1]),
  ];
}

/** EagleView-style text block. */
export function report(facets: Facet[]): string {
  const s = lineLengths(facets);
  const order: EdgeKind[] = ["ridge", "hip", "valley", "rake", "eave", "junction"];
  const label: Record<string, string> = {
    ridge: "Ridges",
    hip: "Hips",
    valley: "Valleys",
    rake: "Rakes",
    eave: "Eaves",
    junction: "Junctions(?)",
  };
  const lines = ["Total Line Lengths:"];
  for (const k of order) {
    if (s[k]) lines.push(`  ${label[k].padEnd(9)}= ${s[k].length.toFixed(1).padStart(6)} ft  (${s[k].count})`);
  }
  const drip = (s.eave?.length ?? 0) + (s.rake?.length ?? 0);
  lines.push(`  ${"Drip edge".padEnd(9)}= ${drip.toFixed(1).padStart(6)} ft  (eaves + rakes)`);
  return lines.join("\n");
}
