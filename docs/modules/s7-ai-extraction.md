# Sprint 7: AI extraction backend (Module 4, part a)

**Status: done.** All four chunks are finished and staged. The developer commits. Next: Sprint 8 (AI review UI).

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s7-ai-extraction` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan): a provider-independent vision interface, a Gemini adapter, a clearly labelled demo adapter, a record of every AI run, Pydantic-validated output with confidence and evidence, handling of timeout, rate limit, unavailable provider and malformed output, contract tests with fixtures, and an opt-in live test. The review UI (accept, edit, reject) is Sprint 8.

## How to resume

1. `git status` and `git log --oneline | head -3`.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Do the first unchecked chunk below. Only that chunk.
4. Run the checks, tick the chunk, add a line under "Log", stage, stop.

## Chunks

- [x] **1. Records, schema, interface, demo adapter.** New module `app/modules/ai`. `AgentRun` table: listing, organisation, requested by, agent name and version, provider, model and model version, input references (media asset IDs and SHA-256, never copies), status `queued`/`running`/`succeeded`/`failed`, attempts, structured output (JSONB), error, started and finished times, link to the `jobs` row. The `jobs` table already plays the "AIJob" role, so there is no separate AIJob table. Pydantic `Extraction` schema: per photo a room type and a list of features (attribute from a fixed set, value, confidence 0 to 1, `uncertain` flag set below a threshold, evidence: media asset ID plus a short visual note). `VisionProvider` protocol and `DemoVisionProvider`, whose output says it is demo output. (Settings moved to chunk 2.) Tests: schema accepts valid and rejects invalid output; demo output validates.
- [x] **2. Gemini adapter.** Settings `GEMINI_API_KEY`, `GEMINI_MODEL`, `AI_TIMEOUT_SECONDS`; `get_provider()` returns Gemini when the key is set, otherwise the demo adapter (no separate on/off setting). REST call with the standard library (no new dependency), structured JSON output requested with a response schema, images sent inline. Typed errors: `ProviderUnavailable`, `ProviderTimeout`, `RateLimited` (with retry-after), `MalformedOutput`. Untrusted content (listing text, image text) never goes into the system instruction. Contract tests against recorded response fixtures in `tests/fixtures/gemini/` (valid, invalid JSON, schema mismatch, 429, 500, timeout). Opt-in live test: `pytest -m live`, skipped without `GEMINI_API_KEY`.
- [x] **3. Extraction job and API.** `POST /api/v1/listings/{id}/ai/extractions` queues an `ai.extract` job for the listing's ready photos (editors only, audited). The handler records an `AgentRun`, calls the provider, validates, stores the result. Timeout and rate limit retry through the job backoff; malformed output retries once, then fails with a clear error on the run. `GET /api/v1/listings/{id}/ai/extractions` lists runs (readers of the listing). Nothing is written to listing fields. `pnpm gen:api`.
- [x] **4. Live check and docs.** Run one real extraction against Gemini with demo photos. ADR 0004 (provider choice, demo mode, what is sent to Google and the free-tier data terms). README and `.env.example`, RBAC matrix, and the sections below.

## Chunk 3 plan (done; kept for reference)

Read first: `app/modules/media/service.py` (`list_media`, `get_content`, `make_thumbnail` and `_thumbnail_failed` as the job pattern), `app/modules/jobs/service.py` (`handler`, `enqueue`, `run_one`), `tests/test_media.py` (fixtures and upload helper).

- [x] a. `app/modules/ai/service.py`: `request_extraction(session, ctx, listing_id) -> AgentRun`. Use `media.service.list_media(session, ctx, listing_id)` (gives 404 when the listing is not visible). Refuse with 403 unless `listings.service.can_edit(ctx, listing)`. Keep only originals with status `ready`; none: 409 or 422 "Add a photo first" (use the `AppError` style in `app/core/errors.py`). Cap at 10 photos (the newest ones). Create `AgentRun(agent="vision_extraction", agent_version="1", inputs=[{"media_asset_id", "sha256"}], status="queued")`, then `jobs.enqueue(session, "ai.extract", {"run_id": str(run.id)}, organisation_id=..., max_attempts=3)`, set `run.job_id`, and call `audit.record(...)` (copy a media upload call).
- [x] b. Same file: `@jobs.handler("ai.extract", on_failed=_extraction_failed)` `run_extraction(session, job)`. Load the run, set `running`, `started_at`, `attempts += 1`. Read the bytes with `media.service.get_content(session, asset_id)` (skip assets deleted since the request). Build `Photo`s and call `get_provider().extract(photos)`. On success, store `output=result.extraction.model_dump(mode="json")`, provider, model, model_version, `succeeded`, `finished_at`. On a `ProviderError` that is not `retryable`, mark the run failed now and return without raising. Otherwise re-raise, so the job backoff retries (30 s doubling, 3 attempts). `_extraction_failed` writes `failed`, the job's `last_error` and `finished_at` onto the run. shortcut: the backoff ignores `RateLimited.retry_after`; use `jobs.enqueue(..., delay=...)` if 429s become common. Never write to listing fields.
- [x] c. `app/modules/ai/schemas.py`: `AgentRunOut` (id, status, agent, agent_version, provider, model, model_version, inputs, output as `Extraction | None`, error, created_at, started_at, finished_at, `is_demo = provider == "demo"`). `app/modules/ai/router.py`: `POST /api/v1/listings/{listing_id}/ai/extractions` (202, returns the run) and `GET` the same path (newest first, readers of the listing; a listing read through `list_media` enforces visibility). Use `require(...)` like `app/modules/media/router.py`. Register in `app/main.py` and replace the `_ai_models` import line there with the router import.
- [x] d. The worker must import the handler: check how `app/worker.py` loads `media.service` handlers and do the same for `app.modules.ai.service`.
- [x] e. `tests/test_ai_extraction.py`: monkeypatch `app.modules.ai.service.get_provider` to a fake. Cover: editor requests, `run_one`, run succeeded with output and `provider`; read-only member gets 403 on POST but can GET; another organisation gets 404; no ready photos gives the refusal; a retryable error leaves the job queued for retry and the run not failed; a non-retryable error fails the run at once; the last attempt failing marks the run failed with the error; demo provider gives `is_demo` true; listing fields are unchanged after a run.
- [x] f. Checks (API, then `pnpm gen:api` and the web checks, since the OpenAPI schema changes). Tick chunk 3, add a log line, stage, stop.

## Conventions to follow (already in the codebase)

- Module layout `app/modules/<name>/{models,schemas,service,router}.py`. A module calls another module's `service`, never its tables. Register routers in `app/main.py`.
- Background work: `jobs.enqueue(...)` in the same transaction; `@jobs.handler(kind, on_failed=...)`. See `docs/modules/s6-media-jobs.md`, "Shared pieces".
- Photos: `media.service.list_media` and `media.service.get_content`. Never send another organisation's media.
- Permissions only in `app/modules/organisations/permissions.py`; keep `docs/security/rbac-matrix.md` in step. Sensitive actions call `audit.record(...)`.
- One additive Alembic migration per chunk that changes tables; read it after autogenerate.
- `.env` holds `GEMINI_API_KEY` and is git-ignored. Never print the key, log it, or put it in a fixture.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest -q
# from apps/web (only if the API schema changed)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk: date, what was done, anything left open)

- 2026-11-17, setup. Root `.env` created from `.env.example` with `GEMINI_API_KEY` (file mode 600). Confirmed ignored by `.gitignore` (`.env`) and never committed. The key was shared in a chat; rotate it before any public demo.
- 2026-11-17, chunk 1 done. `app/modules/ai/{models,schemas,providers}.py`, migration `00d636ea60b1_agent_runs`, `tests/test_ai_schema.py` (7 tests; 106 pass in total). `Extraction` forbids extra fields, limits attributes to observable ones (no room counts or measurements), and marks any feature below 0.6 confidence as uncertain. `check_inputs()` rejects output about photos that were not sent or repeated. Provider errors carry `retryable`. Demo values start with `[Demo] ` and are all uncertain.
- 2026-11-17, chunk 2 done. `app/modules/ai/gemini.py` (REST through `urllib`, key in the `x-goog-api-key` header, low thinking level), `app/modules/ai/service.py` (`get_provider()`), settings `GEMINI_API_KEY` / `GEMINI_MODEL` (default `gemini-3.5-flash`; Google currently serves it as `gemini-3.6-flash`) / `AI_TIMEOUT_SECONDS` (90). Gemini refused the full Pydantic schema ("too many states"), so the request sends a copy without length limits and formats; Pydantic checks them on the answer. Errors: 429 is `RateLimited` with the delay from `Retry-After` or `RetryInfo`; 404, 408 and 5xx are `ProviderUnavailable`; other 4xx and blocked prompts are `ProviderRejected` (not retryable); bad JSON, schema mismatch, unsent photos and early stops are `MalformedOutput`. Fixtures in `tests/fixtures/gemini/` (`valid.json` is a real response). `tests/test_ai_gemini.py` (14 tests; 120 pass). `conftest.py` blanks `GEMINI_API_KEY`, so the normal test run never calls Gemini. `pytest -m live` passed in 18 s. Observed while probing: `gemini-2.5-flash` is closed to new keys (404); `gemini-3.8-flash` answered 503 "high demand" after 84 s; `gemini-3.5-flash` sometimes answered 404 with an empty body and then 200 seconds later. The first live run failed for the same reason. Chunk 3's job retries cover this.
- 2026-11-17, chunk 3 done. `app/modules/ai/service.py` (`request_extraction`, `list_runs`, `ai.extract` handler), `app/modules/ai/router.py` (`POST` 202 and `GET` on `/api/v1/listings/{id}/ai/extractions`), `AgentRunOut` in `schemas.py`, router registered in `app/main.py`. The worker needed no change: it imports `app.main`, which loads the handler. No migration (no table changes). The run takes the newest 10 ready photos; none ready gives 409 `no_photos`. Editors only (`listings.can_edit`), audited as `ai.extraction_requested` in the router like the media routes. Retryable provider errors re-raise into the job backoff (3 attempts); `MalformedOutput` gets one retry only; `ProviderRejected` fails the run at once without a job retry. Photos deleted since the request are skipped; if none are left the run fails. `run.attempts` mirrors `job.attempts`. While a retry is pending the run shows `queued` with no error (the job rollback discards it); open for Sprint 8 if the UI needs "retrying". `tests/test_ai_extraction.py` (10 tests; 130 pass). `pnpm gen:api` updated `apps/web/src/api-schema.d.ts`; web lint, typecheck, tests (37) and build pass.
- 2026-11-17, chunk 4 done. Live check: signed in as `sunrise.agent@demo.example.com` through the API, requested an extraction on a seeded listing (2 photos), ran the worker. Two runs, both `succeeded` on the first attempt with `provider = gemini`, `model_version = gemini-3.6-flash`, in 51 s and 17 s. Gemini returned no features for either photo. The seeded photos are flat drawings of a house, so this is the right answer: it did not invent features. A check with a real interior photo is still to do. `pytest -m live` failed once in 2 s (a transient provider error, as seen in chunk 2) and passed on the rerun in 14 s. Fixed while writing the ADR: chunk 3 sent original files, and originals keep EXIF (GPS, camera). The handler now sends `media.service.without_metadata(data)`: a JPEG of at most 1600 px rebuilt from pixels. New test `test_provider_gets_photos_without_camera_metadata` (131 pass). Docs: ADR 0004, README settings, RBAC matrix (extraction rights, `ai.extraction_requested`). `.env.example` already had the settings from chunk 2.

## What was built

- **Run records** (`app/modules/ai/models.py`): `agent_runs` table. Each run records who asked, the provider, model and model version, the photos sent (asset ID and SHA-256), status, attempts, the validated output, any error and the times.
- **Output format** (`app/modules/ai/schemas.py`): `Extraction`. Per photo there is a list of features: attribute (observable things only), value, confidence, evidence and an `uncertain` flag (below 0.6).
- **Providers** (`app/modules/ai/providers.py`, `gemini.py`): the `VisionProvider` interface, a Gemini adapter (REST through the standard library) and a demo adapter labelled `[Demo]`. Errors are typed and say whether a retry can help.
- **Job and API** (`app/modules/ai/service.py`, `router.py`):
  - `POST /api/v1/listings/{id}/ai/extractions` queues an `ai.extract` job (editors only, audited).
  - `GET` on the same path lists runs, newest first (readers of the listing).
  - Photos are stripped of metadata before they are sent.
  - Nothing is written to listing fields.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Show or review suggestions (Sprint 8) | `GET /api/v1/listings/{id}/ai/extractions`, type `AgentRunOut` in `apps/web/src/api-schema.d.ts`. Show `is_demo` runs as demo output. Show `uncertain` features as uncertain. Link each feature to its photo through `media_asset_id`. |
| Start an extraction from the web app | `POST` on the same path (202). Poll the list until the run is `succeeded` or `failed`, the way the photo gallery polls processing. |
| Another AI task (descriptions, compliance) | A new `agent` name on `AgentRun`, a Pydantic output schema, and a job handler in `app/modules/ai/service.py`. Use `get_provider()` or add a method to the provider interface. Never write to listing fields directly. |
| Send a photo outside the system | `media.service.without_metadata(data)`. Never send an original file. |
| Tests that touch AI | Monkeypatch `app.modules.ai.service.get_provider` with a fake (see `FakeProvider` in `tests/test_ai_extraction.py`). `conftest.py` blanks `GEMINI_API_KEY`. Live tests are `pytest -m live`. |

## Acceptance results

| Criterion (Sprint 7 scope) | Result |
|---|---|
| Provider-independent vision interface | Met. `VisionProvider` has a Gemini adapter and a demo adapter. |
| Clearly labelled demo adapter | Met. Values start with `[Demo] `, all are uncertain, and the API sets `is_demo`. Tested. |
| Every AI run recorded | Met. `AgentRun` stores the provider, model, version, input references, output, error and times. Tested. |
| Validated output with confidence and evidence | Met. Pydantic `Extraction`. Output about photos that were not sent is rejected. Tested. |
| Timeout, rate limit, unavailable provider and malformed output handled | Met. Job retries (3 attempts); malformed output retried once; rejected requests fail at once. Contract tests use recorded fixtures. |
| Opt-in live test | Met. `pytest -m live` passed (once after a transient failure). A live extraction through the API and the worker succeeded twice. |

Checks: API `ruff format --check`, `ruff check`, `mypy`, `pytest` (131 passed). Web lint, typecheck, `vitest` (37) and build passed after `pnpm gen:api` in chunk 3. Chunk 4 did not change the API schema.

## Known limitations

- Not yet tried on a real interior photo. The seeded drawings produce no features.
- Gemini's free tier may use what is sent to improve Google's products. Send demo photos only (ADR 0004). The development key was shared in a chat: rotate it before any public demo.
- Latency was 17 to 51 s for two photos.
- While a retry is pending, the run shows `queued` with no error, because the job rollback discards it.
- The job backoff ignores `Retry-After` on 429.
- Gemini model names change. Set `GEMINI_MODEL` when Google renames or closes one.
- There is no limit on how often an editor can request extractions. Each request costs a provider call.
- There is no web UI yet (Sprint 8).

## Next

Sprint 8: AI review UI (accept, edit, reject suggestions). It should use the shared pieces above.
