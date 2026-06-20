"""Wall derivation (Phase 2).

Walls are NOT returned by any roof API — they are derived (DSM - ground
height x perimeter, plus oblique-photo homography for openings). This is
the product's main differentiation. The pure formulas
(``gross_wall_area``, ``gable_triangle_area``, ``net_siding_area``) already
live in the measurement engine and are unit-tested; the modules here add
the data plumbing (height extraction, opening rectification).
"""
