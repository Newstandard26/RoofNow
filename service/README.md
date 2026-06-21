# roofwall-cv — boundary-recovery service

Runs the DSM → facet-polygons recovery (`recover.py` + `geo.py`) that produces
real ridge/hip/valley/eave/rake **line lengths** on live data. It lives in a
separate service because its deps (~400 MB: numpy/scipy/scikit-image +
GDAL/PROJ) exceed Vercel's 250 MB function limit.

## Endpoints
- `GET /health` → `{status, has_key}`
- `GET /facets?lat=..&lng=..` → `{model, line_lengths, recovery_status}`

## Deploy (Cloud Run)
```bash
gcloud run deploy roofwall-cv \
  --source . \
  --region us-central1 \
  --memory 1Gi --timeout 120 \
  --set-env-vars GOOGLE_MAPS_API_KEY=YOUR_SERVER_KEY \
  --allow-unauthenticated      # or keep private + use IAM/an API gateway
```
Uses the repo-root `Dockerfile`. (Render/Fly work too — same image.)

## Wire it to RoofNow
On the Vercel `roof-now` project, set:
```
ROOFWALL_CV_URL = https://roofwall-cv-XXXX.run.app
```
Redeploy. `/api/measure` live responses will then call this service and include
`line_lengths` (and `recovery_status: ok:<facets>`). If the service is down or
slow, `_live_report` degrades gracefully — the report still renders with
`recovery_status` explaining why (`error:…`, `no_dsm`, etc.).

## Notes
- The same `GOOGLE_MAPS_API_KEY` needs the **Solar API** (Data Layers) enabled.
- Signed Data-Layer URLs expire ~1h; the service downloads them within the request.
- Consider protecting the endpoint (IAM, an allowlist, or a shared secret) since
  each call hits the paid Solar API.
