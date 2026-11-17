# Sprint 13: Semantic search (Module 8)

**Status: done (2026-11-17).** All six chunks are finished. Staged, not committed.

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s13-semantic-search` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan, Module 8): an embedder interface (dimension read from the model, not hardcoded); a Qdrant collection; hybrid filter plus vector retrieval; the tenant and visibility filter applied in the query; match explanations; outbox-driven re-index and removal of stale vectors.

## Design decisions (reversible; made 2026-11-17)

- **Module** `app/modules/search/`. Embedding is a provider behind `Embedder` (`embedder.py`), like the AI providers and the geocoder.
- **Embedder choice is explicit**: `EMBEDDER=demo` (default) or `EMBEDDER=gemini` (needs `GEMINI_API_KEY`). It is not switched on by the key alone, because changing the embedder re-indexes every listing and sends listing text to Google.
- **Demo embedder** (`source="demo"`): feature hashing of words and character trigrams into 256 numbers, normalised. It matches shared words and spellings, not meaning. Every result it feeds says so.
- **Gemini embedder**: `models/{GEMINI_EMBEDDING_MODEL}:batchEmbedContents` over the same REST transport as `gemini.py`, `taskType` `RETRIEVAL_DOCUMENT` for listings and `RETRIEVAL_QUERY` for searches, at most 100 texts per call. The dimension is the length of the vectors the model returns; nothing hardcodes it. A wrong-length or empty answer is `MalformedOutput`.
- **Vectors are tied to their model.** `Embedder.model_key` (e.g. `gemini/gemini-embedding-001/3072`) names the collection. A new key means a new collection and a full re-index; vectors from another key are never compared.
- **Vector store** (chunk 2): interface `VectorStore` with two adapters. `VECTOR_STORE=postgres` (default) keeps vectors in a `listing_vectors` table and scores in Python over the rows the SQL filter allows (enough for a demo; `shortcut:` at ~20k listings). `VECTOR_STORE=qdrant` uses Qdrant's REST API (Docker Compose service for local use, Qdrant Cloud for the live demo).
- **Tenant and visibility filter in the query, twice.** Qdrant gets a payload filter (`organisation_id` equals the caller's, or `visibility` is `network` and status is searchable). The candidate IDs then go through the normal listings visibility query in SQL, so a stale payload can never show a listing the caller may not see.
- **Outbox** (chunk 3): an `outbox_events` row written in the same transaction as a listing or property change. Each subscriber gets its own job per event (`outbox.subscribe(event_kind, job_kind)`). The `search.reindex` job embeds the listing text, and upserts or deletes the vector. Archived, withdrawn and deleted listings lose their vector. S18 and S19 reuse the outbox.
- **Hybrid search** (chunk 4): `GET /api/v1/listings/search?q=` plus the existing listing filters (including the S12 geo filters) and `limit` (1–50, default 20). Filters narrow first (at most 5000 newest candidates); vectors rank. One ranked page, no cursor; `sort` is ignored. Each result carries `score` and `explanation` (matched words, which filters applied, embedder `source` and model).

## Chunks

- [x] **1. Embedder interface and adapters.** `app/modules/search/embedder.py`: `Embedder`, `Embeddings` (with `dimension` and `model_key`), `DemoEmbedder`, `GeminiEmbedder`, `get_embedder()`. Settings `embedder`, `gemini_embedding_model`. No database, no API. `tests/test_embedder.py` with a fake transport.
- [x] **2. Vector store.** `vector_store.py`: `VectorStore` (`ensure`, `upsert`, `delete`, `query` with a filter), `PostgresVectorStore` (migration for `listing_vectors`), `QdrantVectorStore` (REST through the standard library, fake transport in tests). Qdrant service in `docker-compose.yml` under a profile. Settings `vector_store`, `qdrant_url`, `qdrant_api_key`.
- [x] **3. Outbox and re-index.** `outbox_events` table and `outbox.emit(session, kind, ...)`; emitted by `listings.service` on create, update, status and visibility change, and by property address changes. Job `search.reindex`: embed `title`, remarks, property type, locality and city; upsert or delete. A command to re-index everything (model change, backfill). Tests, including that a failed transaction writes no event.
- [x] **4. Hybrid search API.** `GET /api/v1/listings/search` with `q` and the listing filters; tenant and visibility filter in the store query and again in SQL; `score`, `explanation`. Tests: cross-tenant, private listing of another organisation never returned, network listing returned, archived listing gone, geo filter combined. `pnpm gen:api`.
- [x] **5. Web.** Search box "Describe the home" on the listings page; results show the explanation and a "demo embedder: matches words, not meaning" label when `source` is `demo`. Tests.
- [x] **6. Seed, browser check, docs.** Seed re-index; Chrome check at desktop and 375 px; fill in the sections below, README status, `docs/security/rbac-matrix.md`, `docs/HOW_TO_RUN.md`. Run every check.

## Conventions to follow (already in the codebase)

- Jobs: `jobs.enqueue(...)` in the same transaction; `@jobs.handler(kind, on_failed=...)`; handlers safe to run twice (`docs/modules/s6-media-jobs.md`).
- Providers: demo adapter labelled, real adapter behind settings, HTTPS only, errors mapped to `ProviderError` subclasses in `app/modules/ai/providers.py`.
- Gemini REST calls: reuse `GeminiClient`'s transport and `_http_error` in `app/modules/ai/gemini.py`.
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

- 2026-11-17: chunk 1. Embedder interface, demo and Gemini adapters, settings (`EMBEDDER`, `GEMINI_EMBEDDING_MODEL`), tests. `GeminiClient._post` split out of `_generate` so both share the error mapping. Nothing a tester can see yet.
- 2026-11-17: chunks 2–3. `VectorStore` with Postgres (`listing_vectors`) and Qdrant (REST, `docker compose --profile qdrant`) adapters; `outbox_events` and `outbox.emit`/`subscribe`; emits from `listings.service` (create, update with changes, transition, archive, property update); job `search.reindex`; `python -m app.modules.search.cli reindex`. Migration `54337250f867`. Qdrant adapter checked against a real Qdrant v1.13 container (tenant filter, delete, missing collection).
- 2026-11-17: chunk 4. `GET /listings/search` (in `listings/router.py`, before `/{listing_id}`), schemas in `search/schemas.py`, 503 `search_unavailable` when the embedder fails. `tests/test_search.py` (12 tests).
- 2026-11-17: chunk 5. "Describe the home" on the listings page; ranked results with "Why it matched" and the demo label. Web test added.
- 2026-11-17: chunk 6. Seed queues indexing for demo listings that have no outbox event yet. Browser check at desktop and 375 px on a separate `mls_e2e` database (an old worker on `mls` predated the new job kind). Docs updated.

## What was built

- API: `GET /api/v1/listings/search?q=...&<listing filters>&limit=` returns `items` of `{listing, score, explanation: {matched_words, filters, source, model, note}}`.
- Re-index: every listing or property change writes an `outbox_events` row and a `search.reindex` job in the same transaction. The job embeds the title, rooms, type, sale or rent, locality, city and remarks, and upserts the vector; withdrawn, expired and archived listings are removed.
- Stores: `VECTOR_STORE=postgres` (default) or `qdrant` (`QDRANT_URL`, `QDRANT_API_KEY`). One Qdrant collection per embedder model key.
- Web: "Describe the home" on the listings page, ranked results, "Why it matched" column, demo embedder label.
- Command: `python -m app.modules.search.cli reindex` queues every listing (after changing `EMBEDDER` or `VECTOR_STORE`).

## Acceptance results

- Tenant isolation: another organisation's private listings and shared drafts never appear; its shared active listings do (`test_other_organisations_private_listings_never_appear`, live Qdrant check, API check as Harbour Homes).
- Filters combine with ranking, including the geo radius (`test_ranking_explanation_and_filters`).
- Withdrawn and archived listings leave the index; a property address change re-indexes its listings.
- A rolled-back change writes no event and no job.
- Embedder outage gives 503 `search_unavailable`, not a 500.
- All checks pass: API ruff, mypy, alembic check, pytest; web lint, typecheck, test, build.

## Known limitations

- The demo embedder matches words and spellings only; "sea-facing" does not find "ocean view". Results always say so.
- Every listing change re-embeds the listing, even a price edit (a `shortcut:` in `search/service.py`). Fine for the Gemini free tier at demo volume.
- Ranking covers at most the 5000 newest listings that pass the filters (`MAX_CANDIDATES`).
- Postgres store scores in Python (`shortcut:` at about 20k listings; move to Qdrant or pgvector).
- Changing the embedder leaves old vectors in place until re-indexed; they are never compared with the new model's vectors, so search shows fewer results until the worker catches up.
- Two re-index jobs for one listing running at the same moment could leave the older status in the Qdrant payload; the SQL candidate filter still hides anything the caller may not see.
- No pagination; one ranked page of up to 50.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Tell other modules something changed (S18 webhooks, S19 notifications) | `outbox.service.emit(session, kind, organisation_id=, subject_type=, subject_id=, payload=)` in the changing transaction; consumers call `outbox.service.subscribe(event_kind, job_kind)` at import time and register a job handler. Event kinds so far: `listing.changed`, `property.changed`. |
| The listing filter and visibility query without paging | `listings.service.filtered_listings(ctx, filters)` |
| Embed text | `search.embedder.get_embedder().embed(texts, "document" or "query")` |
| Similar listings (e.g. S14 comparables) | `search.vector_store.get_vector_store().query(...)` with SQL-chosen `candidate_ids` |
| Re-index listings | `search.service.enqueue_reindex(session, ids)` |

## Next

Sprint 14: valuation and simulation (Module 9). It closes Phase B.
