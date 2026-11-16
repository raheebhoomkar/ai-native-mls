# Sprint 7: AI extraction backend (Module 4, part a)

**Status: in progress.** Chunk 3 is next.

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
- [ ] **3. Extraction job and API.** `POST /api/v1/listings/{id}/ai/extractions` queues an `ai.extract` job for the listing's ready photos (editors only, audited). The handler records an `AgentRun`, calls the provider, validates, stores the result. Timeout and rate limit retry through the job backoff; malformed output retries once, then fails with a clear error on the run. `GET /api/v1/listings/{id}/ai/extractions` lists runs (readers of the listing). Nothing is written to listing fields. `pnpm gen:api`.
- [ ] **4. Live check and docs.** Run one real extraction against Gemini with demo photos. ADR 0004 (provider choice, demo mode, what is sent to Google and the free-tier data terms). README and `.env.example`, RBAC matrix, and the sections below.

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
