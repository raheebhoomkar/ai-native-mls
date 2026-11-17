# Sprint 20: UX and admin console (Module 13)

**Status: done (2026-11-17).** First sprint of Phase D. The developer asked for the whole sprint in one go. Nothing committed.

Branch: `feature/s6-media-jobs`. Nothing is committed by Claude; the developer commits.

Scope (from the approved plan): role-aware dashboard, platform/MLS admin, audit view, accessibility pass, phone/tablet pass, PWA manifest, loading/empty/offline/failure states, wider end-to-end coverage. The Phase C report adds: put the Monitor, Notifications, API keys and Webhooks pages on the dashboard.

## How to resume

1. `git status` and `git log --oneline | head -3` to see what is committed and what is staged.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Find the first unchecked chunk below. Do only that chunk.
4. Run the checks under "Checks", tick the chunk, add a line under "Log", stage.

## Design decisions (reversible; made 2026-11-17)

- **Dashboard API** `GET /api/v1/dashboard` in a new module `app/modules/dashboard/` (no tables). It reads other modules only through their services. Each part is present only when the caller's permissions allow it, so the screen and the API agree:
  - `listings`: counts by status of the organisation's listings (`listing:read`), and `mine`: counts of listings where the caller is the agent.
  - `review_queue`: findings waiting for the caller (`listing:publish`).
  - `workflows`: counts of the organisation's runs that are active, waiting for review and failed (`listing:read`).
  - `failed_jobs`: failed background jobs (`audit:read`, the Monitor's rule).
  - `unread_notifications`: always.
- **Audit view:** `GET /api/v1/audit-events` gains filters `action` (prefix, such as `listing.`), `actor_user_id`, `target_id`, and returns `actor_name` and `actor_email`. Still `audit:read` and the active organisation only. Sign-in and password events have no organisation, so they never appear in an organisation's log; the page has no area for them.
- **Platform admin:** the Platform page lists the organisations the workspace already loads for its organisation menu (`GET /api/v1/organisations`), with a "Work in it" button that switches to one. No new API.
- **App shell:** skip link to the main content, focus moves to the page heading after navigation, a menu button collapses the nav on phones (below 40rem), an offline banner from `navigator.onLine`, and a clear message when the API cannot be reached.
- **PWA:** `public/manifest.webmanifest`, an SVG icon, and a small service worker that caches the app shell (HTML, JS, CSS) so the app opens offline and says so. API calls are never cached.

## Chunks

- [x] **1. Backend.** Dashboard module and route, audit filters and actor names, tests (tenant isolation and permissions), `pnpm gen:api`.
- [x] **2. Dashboard and audit pages.** `Dashboard.tsx` on `/` (role-aware tiles linking to Listings, Review queue, Monitor, Notifications, Members, API keys, Webhooks, Audit), `Audit.tsx` on `/audit` with filters and "Load more"; nav link with `audit:read`. Tests.
- [x] **3. Shell, accessibility, PWA, platform admin.** Skip link, focus on navigation, phone menu, offline banner, network error text, manifest, icon, service worker, organisations list on the Platform page. Tests.
- [x] **4. End-to-end, browser pass, docs.** Playwright journeys: dashboard and audit at desktop width, phone width menu and listing flow, offline banner. Browser check at 390 px and 768 px. HOW_TO_RUN, this note.

## Conventions to follow (already in the codebase)

- API calls: `api()`, `useAction()`, `useList()` in `apps/web/src/api.ts`.
- Show or hide by `my_permissions`, never by role name. Every control works.
- Types from `apps/web/src/api-schema.d.ts` (`pnpm gen:api` after an API change).
- Module layout `services/api/app/modules/<name>/{router,schemas,service}.py`; another module's data only through its `service`.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/alembic check && .venv/bin/pytest -q
# from apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk: date, what was done, anything left open)
- 2026-11-17, chunk 1 done. `app/modules/dashboard/router.py` (`GET /dashboard`), count helpers `listings.count_by_status`, `workflow.count_by_status`, `jobs.count_failed`, `collaboration.unread_count`; audit filters `action` (prefix, wildcards literal), `actor_user_id`, `target_id`, plus `actor_name`/`actor_email`. `tests/test_dashboard.py` (2). API: 336 passed, ruff, mypy, alembic check clean. `pnpm gen:api` run.
- 2026-11-17, chunk 2 done. `Dashboard.tsx` on `/` under "Your account"; `Audit.tsx` on `/audit` with nav link (`audit:read`); `.tiles` CSS. `Dashboard.test.tsx` (4).
- 2026-11-17, chunk 3 done. Skip link, `main#content` focused after navigation, phone Menu button (below 40rem), `Offline.tsx` banner, clearer "cannot be reached"/"offline" API errors, 44 px touch targets on touch screens, focus outline. PWA: `public/manifest.webmanifest`, `icon.svg`, `icon-192.png`, `icon-512.png`, `public/sw.js` (registered in production builds only). Platform page lists organisations with "Work in it". 3 tests in `App.test.tsx`. Web: 86 tests, lint, typecheck, build.
- 2026-11-17, chunk 4 done. `e2e/console.e2e.ts` (7 journeys + 1 production-only offline-shell test). The two older journeys now click nav links inside the "Main" navigation, since the dashboard adds links with the same words. Browser screenshots at 390 px and 768 px; tile numbers now stay in two columns on phones. Run against the dev server (9 passed, 1 skipped) and the production build served by the API (10 passed). Docs updated.

## Acceptance results (INSTRUCTIONS.md Module 13)

- **Primary workflows on desktop and phone:** the listing journey and the workflow journey run at desktop width; `console.e2e.ts` opens Listings, a listing, Monitor, Notifications and Profile at 390 px, and Listings, Review queue, Audit and Members at 768 px, with no sideways page scrolling.
- **No screen hides essential actions:** on phones the navigation folds behind "Menu" (it never disappears without a way back); wide tables scroll inside their own box.
- **Permissions in navigation and the API:** the dashboard shows a part only when the API returns it, and the API returns it only with the permission (`test_dashboard_parts_follow_permissions`). Agents get no Audit link, and `/audit` says "Only administrators see the audit log."; the API answers 403 (`test_audit_filters_and_actor_names`).
- **End-to-end tests for the main journeys:** 3 Playwright files, 10 tests.
- **Accessible labels, keyboard, clear errors:** skip link, focus moves to the page after navigation, visible focus outline, labelled filters, `role="alert"` on errors, 44 px touch targets on touch screens. Network failures say "The server cannot be reached…" or "You are offline…" instead of a generic message.
- **Loading, empty, offline, failure states:** dashboard "Loading overview…", "Could not load the overview" with "Try again"; audit "No events match."; offline banner; the production build opens offline from the cached app shell.
- **PWA:** manifest, icons (SVG, 192 px, 512 px maskable), service worker caching the app shell only, never API responses.
- All checks pass: API ruff, mypy, alembic check, pytest (336); web lint, typecheck, test (86), build; Playwright as above.

## Known limitations

- No automated accessibility scanner (axe) runs; checks are by hand and through role and label queries in the tests. No screen reader pass with VoiceOver or NVDA.
- The "Install" prompt was not checked by hand; the offline-open test proves the service worker and cache work.
- A new release reaches an open tab on its next page load (navigations are network-first); an old tab keeps old code until then.
- Dashboard numbers load once per visit to Home; they do not refresh on their own.
- The audit page shows record IDs, not record names; only the newest 50 per page with "Load more". Platform-wide events (sign-ins, organisations created) have no screen.
- No native app; the PWA is the phone app. Shared API types would come from `apps/web/src/api-schema.d.ts` if one is added.
- The Platform page has no per-organisation statistics or suspension; the API has none yet.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Counts for a summary | `listings.service.count_by_status`, `workflow.service.count_by_status`, `jobs.service.count_failed`, `collaboration.service.unread_count` |
| Audit search | `audit.service.list_for_organisation(..., action=, actor_user_id=, target_id=)` |
| Offline state in the UI | `OfflineBanner` in `apps/web/src/Offline.tsx`; `api()` errors with status 0 already say offline or unreachable |
| Phone and tablet checks | `expectNoPageOverflow` in `apps/web/e2e/console.e2e.ts` |
| Production-only browser checks | the `@vite/client` script check in `console.e2e.ts` (skips on the dev server) |

## Next

S20 is complete. Stop for the developer's feedback before S21 (hardening): backup and tested restore, monitoring, dependency scanning, load smoke test, dead-letter handling, runbooks, ADR on deferred infrastructure, plus the Phase C additions (cleanup jobs, webhook dead-letter view, unknown job kind alert). The S5 go-live (push and Render Blueprint) is still open.
