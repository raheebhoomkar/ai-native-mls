# Sprint 8: AI suggestion review (Module 4, part b)

**Status: done (2026-11-17).** All four chunks are finished. Staged, not committed.

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
- [x] **2. API.** `POST /api/v1/ai/runs/{run_id}/decisions` (editors, audited, 201). `AgentRunOut` gains `decisions` (by item key) and `can_review`. `GET /api/v1/listings/{id}/features`. Router tests. `pnpm gen:api`.
- [x] **3. Web.** "AI suggestions" panel on the listing detail page, beside the details on wide screens and below them on phones: "Analyse photos" button, progress while the run is queued or running (poll like the photo gallery), errors with retry, suggestions grouped by photo thumbnail with value, confidence, an "Uncertain" badge, a "Demo" badge and the evidence note; Accept, Edit (inline field) and Reject per suggestion; decided suggestions show the decision. "Confirmed features" list. Read-only users see suggestions and decisions without the buttons. Vitest tests.
- [x] **4. Browser check and docs.** Chrome: run an extraction on a seeded listing (demo provider and, if possible, Gemini), accept, edit and reject, check the 390 px layout. Docs: RBAC matrix, README if needed, and the closing sections of this note (what was built, shared pieces, acceptance results, known limitations, next).

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
- 2026-11-17, chunk 2 done. `POST /api/v1/ai/runs/{run_id}/decisions` (201, editors only, audited as `ai.suggestion_decided`). `AgentRunOut` gains `decisions` (by item key) and `can_review`. `GET /api/v1/listings/{id}/features`. `ai.service.decisions(session, run)`. 3 router tests (143 pass). `pnpm gen:api` run.
- 2026-11-17, chunk 3 done. `apps/web/src/ListingSuggestions.tsx`, beside the details from 48rem, below them on narrower screens. `ListingSuggestions.test.tsx` (5 tests; 42 web tests pass).
- 2026-11-17, chunk 4 done. Browser check found that one failed poll (Vite proxy `ECONNRESET`, shown as status 502) stopped polling for good, so the panel stayed on "Waiting to analyse photos…". Fixed: the poll timer now restarts on every load attempt. Regression test added. Docs updated.

## What was built

- **Review records** (`app/modules/review`): `ReviewTask` per subject and `ReviewDecision` per item. A decision is never replaced (unique per task and item); a closed task refuses new decisions.
- **Listing features** (`listing_features`): values a person confirmed, with the photo they came from. Separate from the listing's own fields.
- **API**: decide on a suggestion; runs carry their decisions and whether the caller may review; list a listing's confirmed features.
- **Web**: "AI suggestions" panel on the listing page. Start an analysis, see progress, see errors and retry. Suggestions grouped by photo, with confidence, "Uncertain" and "Demo" badges and the evidence note. Accept, Edit (inline) or Reject each one; decided ones show the decision. "Confirmed features" list. Read-only users see everything without the buttons.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| A person must approve something (Sprints 9, 11, 16) | `review.service.open_task(session, organisation_id=..., subject_type=..., subject_id=...)` (idempotent), `review.service.decide(...)`, `decisions_for`, `close`. Use `item_key=None` for a single-item subject. The calling module checks permissions and applies the effect of a decision. |
| Show decisions on runs | `AgentRunOut.decisions` and `can_review`; item keys are `<media_asset_id>:<feature index>`. |
| Store a confirmed observable fact on a listing | `listings.service.add_feature(...)` / `list_features(...)`; `GET /api/v1/listings/{id}/features`. Never write AI output to listing columns. |
| Poll a background run from the web app | `ListingSuggestions.tsx`: key the poll timer on each load attempt so one failed check does not stop it. |

## Acceptance results

- AI suggestions shown beside the listing: yes, checked in Chrome on "[Demo] 3 BHK apartment near the lake" with a real Gemini run (2 photos, about 40 s).
- Accept and edit in the browser: yes; both appear under "Confirmed features". Reject: covered by API and web tests, not clicked in the browser (the run had only two suggestions).
- Human decision recorded and audited: yes (`review_decisions`, `ai.suggestion_decided`).
- No silent overwrite: test checks the listing is unchanged after decisions; a second decision on an item gets 409.
- Read-only users and other organisations: 403 and 404 in tests; web test checks no buttons.
- Narrow layout: panel stacks below the details. Chrome would not shrink below 606 px here, so 390 px itself was not seen; the stacked layout applies below 768 px (48rem).
- Checks: ruff, mypy, pytest (143 passed); web lint, typecheck, test (42 passed), build.

## Known limitations

- The panel shows only the newest run. Undecided suggestions of an older run stay in the API but are not shown.
- A confirmed feature cannot be removed or added by hand yet.
- Decisions show what was decided, not who decided; the user ID is in the API.
- Decisions on an archived listing are not refused (the API checks edit rights only).

## Next

Sprint 9: redaction (Module 5). It should reuse the review records above for approve and reject.
