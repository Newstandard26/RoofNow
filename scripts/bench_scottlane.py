#!/usr/bin/env python3
"""Benchmark the live roof recovery against the 8656 Scott Lane EagleView report.

Requires network egress to roof-now.vercel.app (enable Full network access on the
cloud environment, then start a fresh session). Usage:

    python scripts/bench_scottlane.py            # production
    python scripts/bench_scottlane.py <base_url> # e.g. a preview deploy

Prints the live /api/recover line lengths + debug vs the EagleView ground truth
with pass/fail per the spec tolerances, so the recovery can be tuned in a tight
loop: edit roofwall/cv/{lines,light}.py -> PR/deploy -> rerun this.
"""
import json
import sys
import urllib.request

# 8656 Scott Lane, Machesney Park, IL 61115
LAT, LNG = 42.3482999, -89.0420952

# EagleView Premium Report ground truth (length_ft, count) + spec tolerances.
TARGETS = {
    "ridge": (49.0, 6, 0.20),
    "hip": (201.0, 14, 0.20),
    "valley": (94.0, 5, 0.25),
    "eave": (240.0, 14, 0.15),
    "rake": (0.0, 0, 0.15),
}
AREA_SLOPED_TARGET = 3006.0   # sq ft
AREA_TOL = 0.05
PITCH_MULT_6_12 = 1.1180      # sqrt(1 + (6/12)^2): plan -> sloped at 6/12


def fetch(base):
    url = f"{base.rstrip('/')}/api/recover?lat={LAT}&lng={LNG}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "https://roof-now.vercel.app"
    data = fetch(base)
    status = data.get("recovery_status")
    ll = data.get("line_lengths") or {}
    dbg = data.get("debug") or {}
    print(f"recovery_status: {status}")
    print(f"debug: {json.dumps(dbg)}\n")

    print(f"{'edge':<8}{'actual ft':>11}{'target ft':>11}{'cnt a/t':>10}{'tol':>7}  result")
    print("-" * 60)
    ok = True
    for kind, (tgt, tcount, tol) in TARGETS.items():
        seg = ll.get(kind) or {}
        act = float(seg.get("length_ft", 0.0))
        cnt = int(seg.get("count", 0))
        if tgt == 0.0:
            passed = act <= 10.0
        else:
            passed = abs(act - tgt) <= tol * tgt
        ok = ok and passed
        print(f"{kind:<8}{act:>11.1f}{tgt:>11.1f}{cnt:>5}/{tcount:<4}{int(tol*100):>5}%  "
              f"{'PASS' if passed else 'FAIL'}")

    plan = float(dbg.get("roof_area_sqft", 0.0))
    sloped = plan * PITCH_MULT_6_12
    area_ok = abs(sloped - AREA_SLOPED_TARGET) <= AREA_TOL * AREA_SLOPED_TARGET
    ok = ok and area_ok
    print("-" * 60)
    print(f"{'area':<8}{sloped:>11.0f}{AREA_SLOPED_TARGET:>11.0f}"
          f"{'':>10}{int(AREA_TOL*100):>5}%  {'PASS' if area_ok else 'FAIL'}"
          f"   (plan {plan:.0f} x {PITCH_MULT_6_12})")
    print(f"\nfacets traced: {dbg.get('n_facets_traced')} (EagleView 14)")
    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
