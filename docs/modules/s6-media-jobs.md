# Sprint 6: Media and job system (Module 3)

**Status: complete** (2026-11-17). Module 3 is complete. Built in five small chunks; the checklist and log below are kept as the record.

Branch: `feature/s6-media-jobs`, cut from `chore/upgrade-python-3.15` (commit `a3cdd7b`), so it carries the Python 3.15 upgrade. Claude does not commit or push; the developer does.

Open from Sprint 5: chunk 4 (go live on Render) is still waiting for the developer. Nothing here depends on it.

## How to resume

1. `git status` and `git log --oneline | head -3`.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Do the first unchecked chunk below. Only that chunk.
4. Run the checks, tick the chunk, add a line under "Log", stage, stop.

## Chunks

- [x] **1. Job system.** New module `app/modules/jobs`: `Job` table (kind, JSON payload, status `queued`/`running`/`succeeded`/`failed`, attempts, max attempts, `run_after`, last error). `enqueue()` adds a job to the caller's transaction. `run_one()` claims the next due job with `FOR UPDATE SKIP LOCKED`, runs its registered handler, retries with backoff, marks it failed after the last attempt, and reclaims jobs whose worker died. `python -m app.worker` polls. Migration. Tests.
- [x] **2. Storage and upload API.** New module `app/modules/media`: `Storage` interface with a local-disk adapter; `MediaAsset` table (listing, organisation, uploader, kind original/thumbnail, original filename, MIME type, size, SHA-256, status, error); upload endpoint for a listing (size limit, allowed MIME types checked against the file's magic bytes, checksum); list a listing's media; signed, expiring download URLs; delete (only who may edit the listing). Tenant and permission tests.
- [x] **3. Thumbnails, retry, retention, S3 adapter.** Upload enqueues a thumbnail job; the handler writes the thumbnail as a separate derivative asset and never changes the original. Failed processing shows its error and can be retried. Deleted media is removed from storage by a job after a retention period. S3-compatible adapter behind the same interface, selected by settings. Run the worker in the Render container.
- [x] **4. Gallery UI.** On the listing detail page: thumbnail gallery, upload with a progress bar per file, per-file errors (too large, wrong type, processing failed) with retry, delete with inline confirm. Only shown to users who may see or edit the listing. Tests.
- [x] **5. Seed, browser check, docs.** Demo photos in the seed (generated, clearly fictional). Browser check at desktop and phone width. Fill in the sections below, README, ADR for the job table (no Redis) and storage choice, Sprint 6 note's shared-pieces table.

## Conventions to follow (already in the codebase)

- Module layout `app/modules/<name>/{models,schemas,service,router}.py`. A module calls another module's `service`, never its tables. Register routers in `app/main.py`.
- Every tenant-owned route uses `require("<permission>")` from `app/modules/organisations/deps.py`. Permissions live only in `app/modules/organisations/permissions.py` (keep `docs/security/rbac-matrix.md` in step).
- Media access follows the listing: who may read the listing may see its media; who may edit it (`listings.service.can_edit`) may upload and delete.
- Sensitive actions call `audit.record(...)`.
- One additive Alembic migration per chunk that changes tables: `.venv/bin/alembic revision --autogenerate -m "..."`, then read it.
- Tests use database `<name>_test` and the fixtures in `tests/conftest.py`.
- Web: see "Shared pieces" in `docs/modules/s4-listing-ui.md`. Run `pnpm gen:api` after API changes.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest -q
# from apps/web (only if the web app or API schema changed)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk: date, what was done, anything left open)

- 2026-11-17, chunk 1 done. `app/modules/jobs/{models,service}.py` (`handler()` decorator, `enqueue`, `run_one`, `retry`, `get_job`; 15-minute lease, backoff 30 s doubling), `app/worker.py` (`python -m app.worker`, stops cleanly on SIGTERM), migration `7a12550ac8bc_jobs`, `tests/test_jobs.py` (9 tests). API: 68 tests pass, ruff, mypy. Worker started and stopped against the dev database. Open: no test runs two workers at once (rows in a rolled-back test transaction are invisible to a second connection); the worker does not run on Render yet (chunk 3). Note: there is no `.env` in the repo root; export `DATABASE_URL` from `.env.example` or copy it to `.env` before running Alembic or the worker. Inherited from `a3cdd7b`: `ruff format --check` fails on `app/core/pagination.py` and `app/modules/auth/service.py`, because ruff `target-version = "py315"` rewrites `except (A, B):` to `except A, B:`, which needs Python 3.14+ while `requires-python = ">=3.13"`. Left for the developer to decide (raise `requires-python`, or lower the ruff target); not changed here.
- 2026-11-17, chunk 2 done. `app/modules/media/{storage,models,service,router}.py`, migration `cf0460ab0865_media_assets`, `tests/test_media.py` (22 tests). Endpoints: `GET`/`POST /api/v1/listings/{id}/media` (raw body, `Content-Type` header, `?filename=`; no multipart, so no new dependency), `DELETE /api/v1/media/{id}` (soft delete, also marks derivatives), `GET /api/v1/media/{id}/content?expires=&signature=` (HMAC link, 15 minutes, no session needed, `nosniff`). JPEG, PNG and WebP only, by magic bytes, and the declared type must match; size limit checked while reading the body. Settings `MEDIA_ROOT`, `MEDIA_MAX_BYTES`, `MEDIA_SIGNING_KEY` (required in production; generated in `render.yaml`). Dockerfile creates a writable `/srv/var/media`. API: 90 tests pass, ruff, mypy. Smoke-tested over HTTP against the dev server. Open: deleted files stay on disk until chunk 3's retention job; an orphan file is possible if the transaction fails after the write (`shortcut:` comment in `service.upload`); Render's free disk is wiped on each deploy, so uploads there are lost until chunk 3's S3 adapter is configured; `pnpm gen:api` not re-run yet (chunk 4).
- 2026-11-17, chunk 3 done. New dependencies `pillow` 13 and `boto3` 1.44. Upload now sets status `processing` and queues `media.thumbnail`: a 480 px JPEG stored as its own `thumbnail` row, built from pixels only (no EXIF), transparent PNGs on white, idempotent. A file Pillow cannot read fails at once (`failed`, "The image could not be read..."); other errors retry 3 times, then `on_failed` marks it `failed` ("Processing failed. Try again."). `POST /api/v1/media/{id}/retry` (editors only; 409 `not_failed` otherwise). `MediaOut.thumbnail_url`. Delete queues `media.purge` after `MEDIA_RETENTION_DAYS` (default 7), which deletes the files and keeps the rows. Jobs: `handler(kind, on_failed=...)`, `enqueue(..., delay=...)`. `S3Storage` selected by `MEDIA_STORAGE=s3` (`MEDIA_S3_BUCKET` required, endpoint and region optional, AWS credentials from the usual variables); tested against a fake client only, never a real bucket. `start.sh` runs the worker in the background beside uvicorn (`shortcut:` comment: not restarted if it crashes). API: 99 tests pass, ruff, mypy. Image built and run against a scratch database: worker started, an uploaded 1600x900 JPEG had its thumbnail within 4 seconds. Open: originals keep their EXIF (including any GPS) and are visible to everyone who can see the listing; stripping it belongs to the media sanitisation work (INSTRUCTIONS 2.1, Sprint 7). Files are served through the API, not by redirect to the bucket.
- 2026-11-17, chunk 4 done. `apps/web/src/ListingMedia.tsx` on the listing detail page ("Photos"): thumbnail grid (click opens the original), "Processing…" placeholder that re-checks every 2 s, failed photos show the error with "Try again", "Remove" with inline confirm, file picker (JPEG, PNG, WebP, several at once) with a progress bar per file and "Retry upload" / "Dismiss" on errors. Upload and remove controls only when the listing's `can_edit`; remove and retry only on items with `can_delete`. `uploadFile()` in `api.ts` (XMLHttpRequest, because fetch cannot report upload progress); shared `toApiError()`. `pnpm gen:api` re-run. `ListingMedia.test.tsx` (6 tests); `ListingPages.test.tsx` stub answers the media list. Web: 37 tests pass, lint, typecheck, build. Open: not yet looked at in a real browser (chunk 5); signed links expire after 15 minutes, so a page left open longer shows broken images until reloaded; no client-side size check (the API's 413 message is shown).
- 2026-11-17, chunk 5 done. Seed adds two drawn, labelled `[Demo]` photos to each demo listing, and replaces them if their files are gone (a fresh container with local storage). The `storage` test fixture moved to `tests/conftest.py`, so no test writes to the developer's media folder. ADR 0003. README, RBAC matrix and Render guide updated. Browser check done (below). API: 99 tests pass; web: 37.

## What was built

- **Job system** (`app/modules/jobs`, `app/worker.py`): Postgres `jobs` table, `FOR UPDATE SKIP LOCKED` claiming, retries with backoff, failure hook, delayed jobs, takeover of jobs whose worker died. See ADR 0003.
- **Media API** (`app/modules/media`): upload a JPEG, PNG or WebP to a listing (raw body; size, declared type and magic bytes checked; SHA-256 stored), list, remove (hidden at once, files deleted after the retention period), retry failed processing, signed download links.
- **Processing**: a 480 px JPEG thumbnail per photo as a separate asset, without camera metadata; unreadable files fail at once with a clear message.
- **Storage**: local disk or any S3-compatible bucket behind one interface.
- **Web** (`apps/web/src/ListingMedia.tsx`): "Photos" on the listing detail page with thumbnails, upload progress per file, errors with retry, processing status that updates itself, removal with confirmation.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Work after the request (AI extraction, re-indexing, webhooks, notifications) | `jobs.enqueue(session, kind, payload, organisation_id=..., delay=...)` in the same transaction as the change; register with `@jobs.handler(kind, on_failed=...)` in the owning module's `service.py`. Handlers must be safe to run twice. Do not add Redis or another queue. |
| Show a job's failure to users | `on_failed` hook writes the failure onto your own record (see `_thumbnail_failed` in `app/modules/media/service.py`) |
| Read or write files | `get_storage()` from `app/modules/media/storage.py`; keys are generated, never taken from users |
| A listing's photos (for AI, redaction, search) | `media.service.list_media(session, ctx, listing_id)` and `media.service.get_content(session, asset_id)`; derivatives are rows with `kind` and `original_id` |
| A new derivative (redacted image, crop) | New `kind` value plus a migration widening `ck_media_assets_kind`; never overwrite an original |
| Upload with progress from the web app | `uploadFile()` in `apps/web/src/api.ts` |
| Tests that touch media | The autouse `storage` fixture in `tests/conftest.py` (a temporary `LocalStorage`); run jobs with `jobs.run_one(db)` |

## Acceptance results

INSTRUCTIONS.md Module 3:

| Criterion | Result |
|---|---|
| Users can upload, view and remove authorised media | Met, in the API and the web app; checked in the browser. |
| Unauthorised users cannot access private assets | Met. Other organisations get 404 for private listings' media; read-only users cannot upload, remove or retry; file links are signed and expire after 15 minutes. Tested. |
| Invalid files are rejected | Met. Wrong type, a declared type that does not match the file, empty and oversized files are refused with a clear message; unreadable images fail processing at once. Tested. |
| Upload state and errors are visible | Met. Progress bar per file, upload errors with retry, "Processing…" and processing failures with "Try again". |
| Local and production storage use the same abstraction | Met. `Storage` interface; local and S3 adapters pass the same test. The S3 adapter is tested against a fake client, not a real bucket. |

Checks run locally: API `ruff format --check`, `ruff check`, `mypy` (strict), `pytest` (99 passed); web `eslint`, `prettier --check`, `tsc --noEmit`, `vitest` (37 passed), `vite build`. Container image built and run against a scratch database: the worker started beside the web server and made a thumbnail within 4 seconds of an upload.

Browser check (Chrome, seeded data, signed in as `sunrise.agent@demo.example.com`, API, worker and web dev server running): the demo listing showed its two seeded photos as thumbnails; an upload of a real PNG together with a fake one showed the fake one's error with "Retry upload" and "Dismiss", while the real one appeared as "Processing…" and then as a thumbnail without a page reload; removal asked for confirmation and the photo disappeared. At a 390 px wide frame the detail page did not scroll sideways and the gallery showed two columns. The worker logged no failed jobs and the API no server errors. The browser window itself cannot be made narrower than about 590 px, so the phone check used a same-origin frame.

## Known limitations

- Original photos keep their EXIF metadata, including any GPS position, and anyone who can see the listing can download them. Stripping it belongs to media sanitisation (INSTRUCTIONS.md 2.1), planned with Sprint 7 or 9.
- Render's free disk is wiped on every deploy, so photos there need a bucket (`MEDIA_STORAGE=s3`); seeded demo photos are re-created at start-up.
- On Render, a crashed worker is not restarted until the container restarts.
- Signed links expire after 15 minutes; a page left open longer shows broken images until reloaded.
- Photos have no order or cover photo, and no caption; the listing table shows no photo.
- Files are read whole into memory and served by the API (limit 10 MB).
- An upload whose transaction fails after the file is written leaves an orphan file.
- The S3 adapter has not been run against a real bucket.
- Not run on GitHub CI yet; Sprint 5's go-live (chunk 4) is still waiting for the developer.

## Next

Sprint 7: AI extraction backend (Module 4, part a). It should reuse the job system and media service above.
