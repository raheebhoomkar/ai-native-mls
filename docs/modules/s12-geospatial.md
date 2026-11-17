# Sprint 12: Geospatial (Module 7)

**Status: done (2026-11-17).** All six chunks are finished. Staged, not committed.

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s12-geospatial` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan, Module 7): coordinates on a property with where they came from; a geocoder interface with an OpenStreetMap Nominatim adapter (within its usage policy) and a labelled demo adapter; a MapLibre map view; radius and bounding-box search; an enrichment adapter that shows its source and retrieval date, or "not available".

## Design decisions (reversible; made 2026-11-17)

- **Module** `app/modules/geo/`. Geocoding is a provider behind `Geocoder` (`geocoder.py`), like the AI providers: `get_geocoder()` picks the adapter from settings.
- **Default is the demo adapter** (`GEOCODER=demo`). It knows the centres of the seeded localities (`precision="locality"`) and of a short list of Indian cities (`precision="city"`), always `source="demo"`. It never invents a street-level point. An unknown city gives no result.
- **Nominatim adapter** (`GEOCODER=nominatim`): HTTPS GET to `/search` with `format=jsonv2`, `limit=1`, `countrycodes` from the address. Usage policy: at most 1 request per second (in-process lock), an identifying `User-Agent` from `GEOCODER_USER_AGENT` (the operator sets a contact there; the default names the app only), no bulk or autocomplete use, results stored on the property so each address is asked once. The result keeps the attribution "© OpenStreetMap contributors".
- **Results are not facts.** Every result carries `source`, `precision` (`address`, `locality`, `city`) and `retrieved_at`. A person can always set or correct a point by hand (`source="manual"`).
- **Location status** (`geo_status`): `pending` (lookup queued), `located`, `not_found`, `failed` (refused, or 3 tries failed; `geo_error` says why). `NULL` for properties made before Sprint 12. A point exists exactly when the status is `located` (check constraint).
- **Location writes do not bump `version`** (`geo/service.py` uses UPDATE statements). An agent who opened the edit form before the lookup finished can still save.
- **When a lookup runs**: on create (service layer, so imports and the seed get it too) and when `address_line1`, `locality`, `city`, `state`, `postal_code` or `country` changes. The old point is cleared at once. A point set by hand (`source="manual"`, precision `address`) is never replaced; set it again to correct it.
- **API**: `PropertyOut` gained `location` (`latitude`, `longitude` as strings, `source`, `precision`, `located_at`, `attribution`), `location_status`, `location_error`. `PUT /api/v1/properties/{id}/location` (`listing:write`, own organisation; others 404).
- **Geo search** (`geo/distance.py`): `within_km` is a bounding box (uses the index) plus haversine in SQL; `haversine_km` is the same formula in Python for `distance_km`. Listings without a point never match a geo filter. Sort order stays the chosen `sort`; there is no sort by distance (keyset pagination works on columns only). Filters are floats with any number of decimals; stored points have 7.
- **Enrichment items**: nearest metro station, schools within 2 km, flood risk. Only the demo enricher exists, and it invents nothing. A property with no point gets "This property has no location yet." A real adapter (e.g. Overpass) is future work.
- **No PostGIS.** Coordinates are two `Numeric` columns; radius search is a bounding-box prefilter plus haversine in SQL. Enough for one MLS; revisit if listings pass ~1 million.

## Chunks

- [x] **1. Geocoder interface and adapters.** `app/modules/geo/geocoder.py`: `GeocodeQuery`, `GeocodeResult`, `Geocoder`, `DemoGeocoder`, `NominatimGeocoder`, `get_geocoder()`. Settings `geocoder`, `nominatim_url`, `geocoder_user_agent`. No database, no API. `tests/test_geocoder.py` with a fake transport.
- [x] **2. Coordinates on properties.** Migration `6c9d4d1f44ae`: `latitude`, `longitude`, `geo_status`, `geo_source`, `geo_precision`, `located_at`, `geo_error` on `properties`, range checks, both-or-neither check, index on (`organisation_id`, `latitude`, `longitude`). In the API schemas. Job `geo.geocode` enqueued on create and when address fields change (skipped when the point is `manual`). `PUT /api/v1/properties/{id}/location` to set a point by hand (editors). Audit `property.geocoded`, `property.location_set`. Tests. `pnpm gen:api`.
- [x] **3. Search.** `near_lat`, `near_lon`, `radius_km` and `min_lat`, `min_lon`, `max_lat`, `max_lon` on `GET /api/v1/listings`; `distance_km` in each item when `near_*` is given. Visibility filters unchanged. Validation (radius 0.1 to 100 km, bbox in range). Tests.
- [x] **4. Enrichment.** `app/modules/geo/enrichment.py`: `Enricher`, `EnrichmentItem` (`value`, `source`, `retrieved_at`, or `reason`), `DemoEnricher` (all "not available"). `GET /api/v1/properties/{id}/enrichment` (`listing:read`, own organisation). Test in `tests/test_geo_location.py`.
- [x] **5. Web.** `MapView.tsx` (`maplibre-gl`, loaded on demand, OSM raster tiles with attribution; says so when WebGL is missing). `ListingLocation.tsx` on the listing page: point, precision, source, date, polling while pending, set by hand (click map or type), neighbourhood list (own organisation only). Listings page: "Show map" and "Search this area" (box filter), "Any area". Tests mock `MapView`.
- [x] **6. Seed, browser check, docs.** Demo geocoder knows the seeded localities; the seed queues lookups for older demo properties. Chrome check at desktop and 375 px. Fill in the sections below, README status, `docs/security/rbac-matrix.md`, `docs/HOW_TO_RUN.md`. Run every check.

## Conventions to follow (already in the codebase)

- Jobs: `jobs.enqueue(...)` in the same transaction; `@jobs.handler(kind, on_failed=...)`; handlers safe to run twice (`docs/modules/s6-media-jobs.md`).
- Providers: demo adapter labelled, real adapter behind settings, HTTPS only, errors mapped to `ProviderError` subclasses in `app/modules/ai/providers.py`.
- Errors use `AppError`; permissions use `require(...)` and `listings.service.can_edit`, never role names.
- Web: `api()`, `useAction()`, `useList()` in `apps/web/src/api.ts`. Run `pnpm gen:api` after API changes.

## How to resume

1. `git status` and `git log --oneline | head -3` to see what is committed and what is staged.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Find the first unchecked chunk above. Do only that chunk.
4. Run the checks below, tick the chunk, add a line under "Log", update `docs/HOW_TO_RUN.md` if the chunk adds something a tester can see, stage, stop.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/alembic check && .venv/bin/pytest -q
# from apps/web (only if the web app or API schema changed)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

- 2026-11-17: chunk 1. Geocoder interface, demo and Nominatim adapters, settings, tests. Nothing a tester can see yet.
- 2026-11-17: chunk 2. Location columns and migration, `geo.geocode` job, manual point endpoint, audit `property.geocoded` and `property.location_set`, `tests/test_geo_location.py`. `test_media_processing` now runs the geocoding job before counting thumbnail jobs. API only; the web shows it in chunk 5.
- 2026-11-17: chunk 3. Radius and box filters, `distance_km`, `tests/test_geo_search.py`. API only.
- 2026-11-17: chunk 4. Enrichment interface, demo enricher, endpoint, test. API only.
- 2026-11-17: chunk 5. Web map, location section, listings map and area search, tests. MapLibre is a 1.1 MB lazy chunk (300 kB gzip); Vite warns about its size.
- 2026-11-17: chunk 6. Demo localities, seed backfill, docs. Chrome check found two bugs, fixed: the neighbourhood list overflowed at 375 px (wrapper `div`s in the `dl` grid), and MapLibre's worker failed to load (`setWorkerUrl` with a `?url` import; the build now emits `maplibre-gl-worker-*.mjs`).

## What was built

- API: `app/modules/geo/` (`geocoder.py`, `service.py`, `distance.py`, `enrichment.py`); location columns on `properties` (migration `6c9d4d1f44ae`); `PUT /api/v1/properties/{id}/location`; `GET /api/v1/properties/{id}/enrichment`; geo filters and `distance_km` on `GET /api/v1/listings`; job `geo.geocode`; audit `property.geocoded`, `property.location_set`.
- Web: `MapView.tsx`, `ListingLocation.tsx`, map and "Search this area" on `Listings.tsx`.
- Settings: `GEOCODER`, `NOMINATIM_URL`, `GEOCODER_USER_AGENT` (`.env.example`).
- Tests: `tests/test_geocoder.py`, `tests/test_geo_location.py`, `tests/test_geo_search.py`; `ListingLocation.test.tsx` and a map test in `Listings.test.tsx`.

## Acceptance results

- Coordinates with their source: yes. Every point has `source`, `precision`, `located_at`, and OSM attribution when it came from Nominatim.
- Geocoder adapter within Nominatim's usage policy: yes, by design (1 request/s per process, identifying User-Agent, one lookup per address change, results stored). Tested with a fake transport only; no live Nominatim call was made.
- MapLibre map view: yes. Checked in Chrome at desktop and 375 px: tiles, markers, attribution, click to open, area search, set by hand, no sideways scroll, no console errors.
- Radius and bounding-box search: yes, with visibility unchanged (tests).
- Enrichment with source and date, or "not available": yes; only "not available" exists today.

## Known limitations

- The Nominatim rate limit is per process; several workers need a shared limiter (`shortcut:` in `geocoder.py`).
- Radius search ignores the 180th meridian (`shortcut:` in `distance.py`). Fine for India.
- OpenStreetMap's public tiles allow light use only (`shortcut:` in `MapView.tsx`); use a tile provider before real traffic.
- The listings map shows the current page of results, not every match.
- No sort by distance.
- No real enrichment source yet.
- A point set by hand is kept when the address changes; the agent must correct it.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Locate a property again after changing its address outside `listings.service.update_property` | `geo.service.request_geocode(session, prop)` |
| Distance or radius filter elsewhere (e.g. S13 hybrid search) | `geo.distance.within_km(lat_col, lon_col, lat, lon, km)` in SQL, `haversine_km` in Python |
| Turn an address into a point | `get_geocoder().geocode(GeocodeQuery(...))`; returns `GeocodeResult` or `None`; raises `ProviderError` subclasses |
