# Sprint 6: Media and job system (Module 3)

**Status: in progress.** Phase B, first sprint. Built in small chunks; do the first unchecked one.

Branch: `feature/s6-media-jobs`, cut from `chore/upgrade-python-3.15` (commit `a3cdd7b`), so it carries the Python 3.15 upgrade. Claude does not commit or push; the developer does.

Open from Sprint 5: chunk 4 (go live on Render) is still waiting for the developer. Nothing here depends on it.

## How to resume

1. `git status` and `git log --oneline | head -3`.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Do the first unchecked chunk below. Only that chunk.
4. Run the checks, tick the chunk, add a line under "Log", stage, stop.

## Chunks

- [x] **1. Job system.** New module `app/modules/jobs`: `Job` table (kind, JSON payload, status `queued`/`running`/`succeeded`/`failed`, attempts, max attempts, `run_after`, last error). `enqueue()` adds a job to the caller's transaction. `run_one()` claims the next due job with `FOR UPDATE SKIP LOCKED`, runs its registered handler, retries with backoff, marks it failed after the last attempt, and reclaims jobs whose worker died. `python -m app.worker` polls. Migration. Tests.
- [ ] **2. Storage and upload API.** New module `app/modules/media`: `Storage` interface with a local-disk adapter; `MediaAsset` table (listing, organisation, uploader, kind original/thumbnail, original filename, MIME type, size, SHA-256, status, error); upload endpoint for a listing (size limit, allowed MIME types checked against the file's magic bytes, checksum); list a listing's media; signed, expiring download URLs; delete (only who may edit the listing). Tenant and permission tests.
- [ ] **3. Thumbnails, retry, retention, S3 adapter.** Upload enqueues a thumbnail job; the handler writes the thumbnail as a separate derivative asset and never changes the original. Failed processing shows its error and can be retried. Deleted media is removed from storage by a job after a retention period. S3-compatible adapter behind the same interface, selected by settings. Run the worker in the Render container.
- [ ] **4. Gallery UI.** On the listing detail page: thumbnail gallery, upload with a progress bar per file, per-file errors (too large, wrong type, processing failed) with retry, delete with inline confirm. Only shown to users who may see or edit the listing. Tests.
- [ ] **5. Seed, browser check, docs.** Demo photos in the seed (generated, clearly fictional). Browser check at desktop and phone width. Fill in the sections below, README, ADR for the job table (no Redis) and storage choice, Sprint 6 note's shared-pieces table.

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
