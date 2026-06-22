# Roof line-length recovery — tuning guide & state

Goal: make `/api/recover` line lengths match the **8656 Scott Lane** EagleView
Premium Report. Validate with `python scripts/bench_scottlane.py` (needs egress
to roof-now.vercel.app — set the cloud env Network access to **Full**, then start
a fresh session).

## EagleView ground truth (benchmark)
- Roof area **3,006 sq ft** (sloped); facets **14**; predominant pitch **6/12**.
- Ridges **49 ft** (6) · Hips **201 ft** (14) · Valleys **94 ft** (5) ·
  Rakes **0 ft** · Eaves **240 ft** (14). Drip edge 240. Complexity **Normal**.
- Property: lat 42.3482999, lng -89.0420952.
- Tolerances: area ±5%, ridge ±20%, hip ±20%, valley ±25%, eave ±15%, rake ≈0.

## Pipeline (lightweight, in the Vercel function)
1. `roofwall/cv/light.build_model_light` — download Solar buildingInsights +
   dataLayers (DSM + mask GeoTIFFs), `geotiff_to_local` (UTM/Mercator -> feet).
2. `recover_light`:
   - `_merge_priors` collapse near-duplicate Solar planes;
   - EM: `assign_pixels` (nearest plane by residual) -> `_fit_plane` -> re-merge;
   - prune planes owning < `min_keep_sqft`;
   - `_smooth_labels` (majority filter) so facets are solid blobs;
   - trace facet polygons (contourpy + Douglas-Peucker) for the diagram.
3. `roofwall/cv/lines.measure_lines` — **line lengths from plane geometry**:
   - interior edges = `_interior_segments`: project shared-border pixels onto the
     two planes' intersection line, split into contiguous runs (gap break),
     classify convex (ridge/hip) vs concave (valley);
   - eave/rake = outer outline, split where the bounding facet changes.
4. `debug` block on `/api/recover`: n_planes_kept, n_facets_traced, roof_area_sqft
   (PLAN area; sloped = plan x pitch_mult), facet_areas_sqft, grid, res_ft.

## Tuning knobs (all in `recover_light` / `measure_lines` kwargs)
- `min_keep_sqft` (40) — drop tiny planes; raise to merge noise, lower to keep
  small real facets (EagleView has 14 — we trace ~10, so maybe too aggressive).
- `_merge_priors` `slope_tol`/`z_tol` — over-merge vs fragment.
- `smooth_iters` (2) — more = cleaner regions but erodes thin facets.
- `_interior_segments` `gap_ft`/`min_len_ft`/`max_perp_ft` — control edge
  splitting, minimum edge, and the 2-D-patch reject.
- `_FLAT_SLOPE` in lines.py — ridge(level) vs hip(sloped) threshold.

## Last live numbers (pre-#34, from debug PDF)
area 4003 (fill bug, reverted in #34); ridge 544, hip 322, valley 519(20),
eave 157, rake 44. Interior ~4x inflated from min->max span fusing borders —
addressed by `_interior_segments` clustering (#34). **Re-run the bench after the
#34 deploy to get fresh numbers and continue.**

## Loop
1. `python scripts/bench_scottlane.py` — see actual vs target.
2. Adjust knobs / algorithm in `roofwall/cv/lines.py` or `light.py`.
3. Keep synthetic tests green: `pytest roofwall/cv` (hip/gable ground truth +
   noisy-DSM in `test_lines.py` / `test_light.py`).
4. PR -> squash-merge to main -> Vercel auto-deploys -> re-run bench.
