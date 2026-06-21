# roofwall-cv recovery service (Cloud Run / Render / Fly).
# Vercel ignores this file; it's only for the separate CV service that runs the
# heavy geospatial recovery (rasterio/scikit-image/shapely) that can't fit in a
# Vercel function.
FROM python:3.11-slim

WORKDIR /app
COPY . /app

# rasterio + pyproj wheels bundle GDAL/PROJ, so no apt GDAL is needed.
RUN pip install --no-cache-dir ".[cv,api]"

ENV PORT=8080
# Cloud Run sets $PORT; default 8080 for local `docker run`.
CMD ["sh", "-c", "uvicorn service.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
