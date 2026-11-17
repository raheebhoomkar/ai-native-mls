# Sprint 8: AI suggestion review (Module 4, part b)

**Status: in progress.** Chunk 1 is done. Chunk 2 (API) is next and not started.

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s8-ai-review` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan and INSTRUCTIONS.md Module 4): show AI suggestions beside the listing; an authorised user accepts, edits or rejects each one; the human decision is recorded; no AI result silently overwrites agent-entered data. Build the generic `ReviewTask` / `ReviewDecision` records that Sprints 9, 11 and 16 reuse.

## Design decisions (reversible; made 2026-11-17)

- **Where accepted values go.** The listing has no columns for flooring, appliances and the other observable features, and AI must never write to agent-entered columns (bedrooms, area, remarks). So accepted or edited suggestions become rows in a new `listing_features` table (listing, attribute, value, source `ai_reviewed`, the photo it came from, who confirmed it). Listing columns are never touched. Agents entering features by hand is out of scope for now.
- **Generic review records** in a new `review` module:
  - `ReviewTask`: organisation, `subject_type` (here `agent_run`), `subject_id`, status `open`/`closed`, created and closed times. One task per succeeded run that has suggestions, opened by the extraction job.
  - `ReviewDecision`: task, `item_key` (here `<media_asset_id>:<feature index>`; null for single-item subjects later), decision `accepted`/`edited`/`rejected`, the suggested value, the final value, an optional note, who decided and when. One decision per item (unique), so a decision is never silently replaced.
  - The task closes when every item has a decision. The AI module decides that, not the review module.
- **Who may decide:** editors of the listing (`listings.can_edit`), the same rule as requesting an extraction. Audited as `ai.suggestion_decided`.
- **Demo runs** can be reviewed like real ones, but values accepted from a demo run keep their `[Demo] ` prefix, so they stay visibly fake.

## How to resume

1. `git status` and `git log --oneline | head -3`.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Do the first unchecked chunk below. Only that chunk.
4. Run the checks, tick the chunk, add a line under "Log", stage, stop.

## Chunks

- [x] **1. Records and service.** New module `app/modules/review` (`models.py`, `service.py`: `open_task`, `get_task_for`, `decide`, `decisions_for`, `close`). `ListingFeature` model and `add_feature` / `list_features` in `app/modules/listings`. One migration for the three tables. The `ai.extract` handler opens a review task when a run succeeds with at least one feature. `ai.service.decide(session, ctx, run_id, item_key, decision, value, note)`: checks the run is visible and editable, the item exists, the value is valid (1 to 120 characters), records the decision, adds a listing feature on accept or edit, closes the task when all items are decided. Tests: accept, edit, reject; second decision on the same item is refused (409); read-only member 403; other organisation 404; listing columns unchanged; task closes after the last item.
- [ ] **2. API.** `POST /api/v1/ai/runs/{run_id}/decisions` (editors, audited, 201). `AgentRunOut` gains `decisions` (by item key) and `can_review`. `GET /api/v1/listings/{id}/features`. Router tests. `pnpm gen:api`.
- [ ] **3. Web.** "AI suggestions" panel on the listing detail page, beside the details on wide screens and below them on phones: "Analyse photos" button, progress while the run is queued or running (poll like the photo gallery), errors with retry, suggestions grouped by photo thumbnail with value, confidence, an "Uncertain" badge, a "Demo" badge and the evidence note; Accept, Edit (inline field) and Reject per suggestion; decided suggestions show the decision. "Confirmed features" list. Read-only users see suggestions and decisions without the buttons. Vitest tests.
- [ ] **4. Browser check and docs.** Chrome: run an extraction on a seeded listing (demo provider and, if possible, Gemini), accept, edit and reject, check the 390 px layout. Docs: RBAC matrix, README if needed, and the closing sections of this note (what was built, shared pieces, acceptance results, known limitations, next).

## Conventions to follow (already in the codebase)

- Module layout `app/modules/<name>/{models,schemas,service,router}.py`. A module calls another module's `service`, never its tables. Register routers and models in `app/main.py`.
- Permissions only through `require(...)` and `listings.can_edit`; keep `docs/security/rbac-matrix.md` in step. Sensitive actions call `audit.record(...)` in the router.
- One additive Alembic migration per chunk that changes tables; read it after autogenerate.
- Runs and their output: `docs/modules/s7-ai-extraction.md`, "Shared pieces".
- Web: polling and gallery patterns in `apps/web/src/ListingMedia.tsx`; API client in `apps/web/src/api.ts`.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest -q
# from apps/web (only if the API schema or web code changed)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk: date, what was done, anything left open)

- 2026-11-17, chunk 1 done. New module `app/modules/review` (`ReviewTask`, `ReviewDecision`, service `open_task`, `get_task_for`, `decisions_for`, `decide`, `close`). `ListingFeature` in `app/modules/listings/models.py`, with `list_features` and `add_feature` in the listings service (editors only; the same attribute and value in any case is kept once). Migration `0a9be0054641_review_tasks_listing_features` (applied to the dev database). The `ai.extract` handler opens a task when a run succeeds with at least one suggestion. `ai.service.items(run)` gives the suggestions by key; `ai.service.decide(...)` records the decision, adds a listing feature on accept or edit, and closes the task after the last item. A second decision on the same item is refused with 409 `already_decided` (unique constraint with NULLS NOT DISTINCT). Other organisations get 404, readers and non-owning agents 403. `tests/test_ai_review.py` (10 tests; 140 pass). No API routes yet, so no `pnpm gen:api`.
