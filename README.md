# roofwall

Turn a property address into a contractor-grade **roof + wall measurement
report** — per-facet area, pitch, azimuth, roofing squares, and (later)
wall areas with window/door openings subtracted.

Target accuracy: **< 3% area error** vs. ground truth (matches EagleView
~98.5%).

## Why the stack is what it is

Three data paths, blended, built in order:

1. **Google Solar API** — instant georeferenced roof geometry
   (pitch/azimuth/area per segment). Fastest path to a working report.
   *(Primary, Phase 1.)*
2. **USGS 3DEP LiDAR + own plane-fitting** — free, public-domain, no
   resale restriction. Fills Solar coverage gaps; the margin play at
   scale. *(Phase 2.)*
3. **Drone / ground photogrammetry** — sub-cm, IP-clean, owned data, for
   complex/disputed/high-value jobs. *(Phase 3.)*

Walls are **not** returned by any API — they are derived (DSM − ground
height × perimeter, plus oblique-photo homography for openings). That's the
main build work and the product's differentiation.

## Architecture

The **measurement engine is pure** (geometry in, numbers out) so it can be
fed by any of the three data paths and unit-tested in isolation.

```
address ─> geocode ─> [Solar API] ─> roof segments (pitch/az/area) ─┐
                  └──> [3DEP LiDAR] ─> plane-fit ─> segments (fallback)│
                            footprint + DSM ─> wall heights & areas    │
                       oblique photo ─> homography ─> openings         │
                                  measurement engine (pure formulas) ──┤
                                          branded PDF / JSON report ◄───┘
```

## Layout

```
roofwall/
  measurement/   # pure formulas + geometry (no I/O) — built & tested FIRST
  sources/       # solar.py (Phase 1), geocode.py, lidar.py/footprints.py (Phase 2)
  walls/         # height.py, openings.py (Phase 2)
  report/        # render.py (JSON/text), pdf.py (optional reportlab)
  api/           # main.py (FastAPI)
  cli.py         # `roofwall measure "<address>"`
```

## Status

| Phase | Scope | Status |
|------|-------|--------|
| 0 | Scaffold + pure measurement engine + unit tests vs. reference tables | ✅ Done |
| 1 | Solar API client → engine → JSON/text report + CLI + FastAPI | ✅ Done (needs API key & ground-truth tuning) |
| 2 | LiDAR plane-fit, wall heights/areas, opening rectification, QA flags | 🟢 Core math done & tested; only raster/EPT/image **I/O** stubbed |
| 3 | Drone photogrammetry, ML facet extraction, integrations | ⬜ Not started |

Phase 2's measurement core is implemented in numpy and tested with synthetic
data:
- **`sources/lidar.py`** — SVD plane fitting, RANSAC plane segmentation,
  plane → pitch/azimuth/area, and `facets_from_points()` → `FacetMeasurement`
  (with a fit-quality confidence that drives the human-QA flag).
- **`walls/height.py`** — `building_height` (DSM−DTM) and a per-elevation
  **N/S/E/W** gross-wall breakdown from a footprint + eave height, plus gable
  triangles → net siding area.
- **`walls/openings.py`** — a pure-numpy DLT **homography** to rectify an
  oblique façade photo and measure window/door openings in real feet.

What's left in Phase 2 is only the heavy **I/O at the edges** — reading 3DEP
EPT point clouds (`pdal`/`open3d`, `lidar-io` extra), sampling DSM/DTM
rasters (gdal), and warping image pixels (`opencv`, `walls-io` extra). Those
functions are stubbed with clear errors; the math they feed is done.

## Quickstart

```bash
pip install -e .                       # core (pure-Python engine + Solar client)
pip install -e '.[report,api,lidar,walls,dev]'   # + PDF, FastAPI, numpy, pytest

python -m pytest                       # 100+ tests, no network or API key

export GOOGLE_MAPS_API_KEY=...         # never commit this
roofwall measure "1600 Pennsylvania Ave NW, Washington DC"
roofwall measure --lat 38.8977 --lng -77.0365 --json

uvicorn roofwall.api.main:app --reload # GET /measure?address=...
```

The engine and all parsing logic are tested **offline** — the Solar client
and geocoder take an injectable `http_get`, so no key or network is needed
to run the suite.

## Measurement formulas

All implemented and unit-tested against the spec's reference tables
(pitch multipliers `3/12=1.031 … 12/12=1.414`; hip/valley factors
`4/12=1.453 … 12/12=1.732`):

```
roofing_square   = 100 sq ft
squares          = sloped_area_sqft / 100
pitch_multiplier = sqrt(1 + (rise/run)^2)        # plan -> sloped
hip_valley_factor= sqrt((rise/run)^2 + 2)
rake_length      = horizontal_run * pitch_multiplier
order_area       = roof_area * (1 + waste_pct)
gross_wall_area  = 2 * height * (length + width)
gable_triangle   = (gable_width * gable_height) / 2
net_siding_area  = (gross - openings) * (1 + waste)
```

Solar API returns metric — converted at the boundary (`m² × 10.7639`,
`degrees → run=12, rise=12·tan(deg)`).

## Constraints & gotchas

- **Licensing.** Do *not* build a resale database of Google/Nearmap
  content. Derived measurements inside the product are fine; redistributing
  their imagery/data is not. Public-domain USGS data has no such
  restriction.
- **Coverage.** Solar API is gappy rurally — `findClosest` 404 raises
  `CoverageError`, the signal to fall back to LiDAR (Phase 2).
- **Accuracy degraders.** Tree canopy, stale imagery, complex roofs — track
  capture date and flag low-confidence facets for human QA.
- **Secrets.** `GOOGLE_MAPS_API_KEY` lives in env vars, never committed
  (see `.gitignore`).
