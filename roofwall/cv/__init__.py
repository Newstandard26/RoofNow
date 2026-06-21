"""Facet boundary recovery: Solar segments / LiDAR -> BuildingModel.

Produces the real per-facet 3D polygons that the edge classifier needs to
output true line lengths on live data. The plane math here is pure Python and
unit-tested; the raster / point-cloud steps require geospatial libraries
(rasterio, scikit-image, scipy, shapely / pdal, open3d) and live data
downloads, and are deliberately stubbed rather than faked.
"""
