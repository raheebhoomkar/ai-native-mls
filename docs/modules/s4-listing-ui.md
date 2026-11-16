# Sprint 4: Listing UI (Module 2, part b)

**Status: complete** (2026-11-17). Module 2 is complete. Built in four small chunks; the checklist and log below are kept as the record.

Branch: `feature/m2b-listing-ui` (from the Sprint 3 commit). Nothing is committed by Claude; the developer commits.

## How to resume

1. `git status` and `git log --oneline | head -3` to see what is committed and what is staged.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Find the first unchecked chunk below. Do only that chunk.
4. Run the checks listed under "Checks", tick the chunk, add a line under "Log", stage, stop.

## Chunks

- [x] **1. Types and listing table.** Generate TypeScript types from the API's OpenAPI schema into `apps/web/src/api-schema.d.ts` (`pnpm gen:api`). New page `apps/web/src/Listings.tsx` at route `/listings`: table (title, status, price, type, location, bedrooms, agent, organisation), filters (`q`, status, scope, city, min/max price, sort), "Load more". Nav link shown with `listing:read`. Component tests.
- [x] **2. Listing detail.** Route `/listings/:id` in `apps/web/src/ListingDetail.tsx`: property facts, price, status, agent, status history (owning organisation only), one button per `allowed_transitions` entry (sold asks for the price; any can take a reason). Table rows link to it. Handle 404 and `409 version_conflict` (reload prompt). Tests.
- [x] **3. Create and edit forms.** `/listings/new`: pick an existing property or enter a new one, then listing fields. `/listings/:id/edit`: listing fields (`PATCH` with `version`) and property fields (`PUT` with `version`). Shown only when `can_edit` / `listing:write`. Archive button with inline confirm. Tests.
- [x] **4. Seed, responsive pass, docs.** Add a few clearly fictional demo properties and listings to `services/api/app/seed.py` (several statuses, one `network`). Check the three screens at phone width (table scrolls in `.table-scroll`, forms single column). Fill in the sections below, update README status and the Sprint 3 note's "No screens yet". Run every check.

## Conventions to follow (already in the codebase)

- API calls: `api()`, `useAction()`, `useList()` in `apps/web/src/api.ts`. `useList(path, reloadKey)` refetches when `path` changes, so put filters in the path's query string.
- Routes for signed-in pages go in `apps/web/src/Workspace.tsx`; it passes `me` and the current `organisation` (with `my_permissions`).
- Show or hide by `my_permissions`, and by each listing's `can_edit` and `allowed_transitions`. Never by role name.
- Money and area arrive as strings. Format for display only; send back strings.
- No control without a working action. A chunk must not link to a page a later chunk builds.
- Tests: `apps/web/src/App.test.tsx` pattern (`stubApi` with one handler per `METHOD /path`). Put listing tests in a new `apps/web/src/Listings.test.tsx`; move `stubApi` and fixtures to `apps/web/src/test-utils.tsx` when the second test file needs them.
- API reference for this sprint: `docs/modules/s3-listings-backend.md`.

## Checks

```bash
# from apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
# from services/api (only if the API or seed changed; needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest -q
```

## Log

(one line per finished chunk: date, what was done, anything left open)

- 2026-11-17, chunk 1 done. `pnpm gen:api` writes `src/api-schema.d.ts` (re-run after any API change; `Listing` type is exported from `Listings.tsx`, as are `STATUS_LABELS` and `formatMoney`). `Listings.tsx` + route + nav + `.filters` CSS + `Listings.test.tsx` (5 tests, own small `stubApi`). Web: 18 tests pass, lint, typecheck, build. Open: table rows are not links yet (chunk 2 adds them); not looked at in a real browser; the dev database has no listings until chunk 4 seeds some, so the page shows "No listings match." unless you create one through `/api/v1/docs`.
- 2026-11-17, chunks 2 and 3 done. `ListingDetail.tsx` (facts, transition buttons from `allowed_transitions`, sold price, archive with confirm, history, 404 and version-conflict handling), `ListingForm.tsx` (`NewListing`, `EditListing`; listing and property saved separately, each with its own `version`), routes in `Workspace.tsx`, table rows and "New listing" link, `ListingPages.test.tsx` (13 tests). `describeError` now names the field in validation messages. Web: 31 tests pass, lint, typecheck, build. Open: reassigning the listing agent has no UI (API supports it).
- 2026-11-17, chunk 4 done. Five fictional `[Demo]` listings in `app/seed.py`, created through the real lifecycle. Tests moved to their own database (`<name>_test`, created by `tests/conftest.py`), because seeded shared listings changed test counts. Browser check done (see below). Docs updated.

## What was built

- `/listings`: table with filters, sort and "Load more".
- `/listings/:id`: property facts, price, status, agent, visibility, remarks, status history, one button per allowed status change, archive.
- `/listings/new`: draft listing on a new or an existing property.
- `/listings/:id/edit`: listing details and property details, saved separately.
- TypeScript types generated from the API schema: `pnpm gen:api` writes `apps/web/src/api-schema.d.ts`. Re-run it after any API change.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| API response and request types | `components["schemas"][...]` from `apps/web/src/api-schema.d.ts`; do not hand-write them |
| Listing type, status labels, price display | `Listing`, `STATUS_LABELS`, `formatMoney` from `apps/web/src/Listings.tsx` |
| Multi-field form layout | `<form className="wide">` with `<div className="fields">` and `Field` (see `ListingForm.tsx`) |
| Row of buttons and links | `<div className="actions">` |
| `409 version_conflict` | Catch `ApiError` with `code === "version_conflict"` and offer a reload; never retry silently |
| Page test with a stubbed API | `stubApi` route map in `apps/web/src/ListingPages.test.tsx` |
| Test data in the API suite | Tests use database `<name>_test`; never assume the developer's database is empty |

## Acceptance results

INSTRUCTIONS.md Module 2:

| Criterion | Result |
|---|---|
| An authorised agent can create and edit a listing | Met, in the UI and the API. |
| A listing is linked to the correct property, agent and brokerage | Met (Sprint 3). Shown on the detail page. |
| Invalid status transitions are rejected | Met (Sprint 3). The UI offers only the changes the API allows for the caller. |
| Listing history is visible to authorised users | Met. Shown to the owning organisation only. |
| Search and filters work against persisted data | Met. |
| Role and tenant permissions are tested | Met (Sprint 3 API tests; UI tests for hidden controls). |
| Desktop listing table, detail and create/edit forms; responsive | Met. |

Checks run locally: web `eslint`, `prettier --check`, `tsc --noEmit`, `vitest` (31 passed), `vite build`; API `ruff format --check`, `ruff check`, `mypy` (strict), `pytest` (55 passed, twice, with a seeded developer database).

Browser check (Chrome, seeded data, signed in as `sunrise.admin@demo.example.com`): the listing table rendered with all five visible listings, including the one shared by Harbour Homes; at a 390 px wide viewport none of `/`, `/listings`, a listing's detail page, its edit page, `/listings/new`, `/members` or `/profile` scrolled sideways, and no element outside a table's own scroll box extended past the screen edge. The server log showed no errors. Forms were not submitted by hand in the browser; submission is covered by component tests.

## Known limitations

- Reassigning the listing agent has no UI (the API supports it).
- No screen to browse, edit or archive properties on their own; a property is edited from one of its listings.
- The "existing property" menu on the new-listing form holds at most 100 properties and has no search.
- Filters are not kept in the URL, so they reset when you leave the page.
- Archived listings cannot be listed in the UI (the API has `include_archived`).
- Prices display without decimals; the stored value keeps them.
- The page background follows the browser's light or dark setting; there is no design system yet (Sprint 20).
- No automated browser end-to-end test yet (Sprint 5).
- Not run on GitHub CI yet.

## Next

Sprint 5: early live demo (Render deploy, demo seed, one Playwright journey). It is the last sprint of Phase A; a phase report and feedback gate follow it.
