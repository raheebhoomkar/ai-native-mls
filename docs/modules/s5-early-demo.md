# Sprint 5: Early live demo

**Status: built and verified locally; not deployed.** Chunks 1–3 are done. Chunk 4 waits for the developer to push and create the Render Blueprint. To resume: check whether a live URL exists; if so, do chunk 4.

Branch: `feature/s5-early-demo` (from the Sprint 4 commit). Claude does not commit or push; the developer does.

## Division of work

Claude cannot sign in to Render or push to GitHub. So:

- **Claude:** container image, `render.yaml`, production settings, browser end-to-end test, deployment guide, all verified locally.
- **Developer:** push the branch, create the Blueprint in the Render dashboard, read the generated demo password there. Steps are in `docs/deployment/render.md` (written in chunk 3).

## How to resume

1. `git status` and `git log --oneline | head -3`.
2. `docker compose up -d --wait`. Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Do the first unchecked chunk below. Only that chunk.

## Chunks

- [x] **1. Deployable image.** One container serves the API and the built web app (same origin, so the session cookie and `/api` paths work unchanged). `Dockerfile`, `.dockerignore`, `services/api/start.sh` (migrate, optional demo seed, start). Settings: accept `postgres://` and `postgresql://` URLs, `WEB_DIST_DIR`, `SEED_DEMO_DATA`, `SEED_PASSWORD`. Seed allowed in production only with both seed settings. `render.yaml`. Tests. Build and run the image locally against a scratch database.
- [x] **2. Browser end-to-end test.** Playwright in `tests/e2e`: sign in, create a listing, find it by search, submit for review. Runs against `E2E_BASE_URL` (local dev server by default, the live demo when set). CI job that starts the stack and runs it.
- [x] **3. Guide, ADR, phase report.** `docs/deployment/render.md` with exact developer steps and rollback; ADR for the single-container decision; README; fill in results below; Phase A report for the developer.
- [ ] **4. (Developer, then Claude) Go live.** Developer pushes and creates the Blueprint. Claude then runs the end-to-end test against the live URL and records the URL in README.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest -q
# from apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk)

- 2026-11-17, chunk 1 done. `Dockerfile`, `.dockerignore`, `services/api/start.sh`, `render.yaml`, settings (`WEB_DIST_DIR`, `SEED_DEMO_DATA`, `SEED_PASSWORD`, URL normalisation), static serving in `app/main.py`, seed production gate. API: 59 tests pass. Image built and run locally like Render (`PORT=10000`, `postgres://` URL, scratch database): health 200, web app and assets served, API docs 404 in production, published seed password refused, generated one accepted, `Secure` cookie, runs as non-root, password absent from logs, forwarded client IP recorded. `render.yaml` itself is not validated until Render reads it.
- 2026-11-17, chunk 2 done. `@playwright/test`, `apps/web/playwright.config.ts`, `apps/web/e2e/journey.e2e.ts`, `pnpm e2e`, CI job `e2e` (builds the image, seeds, runs the journey). Passed locally in Chrome against the container image with a scratch database. The CI job itself has never run.
- 2026-11-17, chunk 3 done. `docs/deployment/render.md`, ADR 0002, README, `.env.example`.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| New setting | Add to `Settings` in `app/core/config.py`, `.env.example`, README table, and `render.yaml` if the demo needs it |
| Something that must run before the server starts | `services/api/start.sh` |
| A second process from the same image (the worker, Sprint 6) | Same image, different command; add a service to `render.yaml` |
| Browser test of a new journey | New `*.e2e.ts` in `apps/web/e2e`; sign in with `E2E_EMAIL` / `E2E_PASSWORD`; clean up what it creates |
| Check the deployable image locally | "Running the same image locally" in `docs/deployment/render.md` |

## Results

Plan items for Sprint 5:

| Item | Result |
|---|---|
| Render deploy of web + API + Postgres | **Prepared, not done.** Needs the developer's Render sign-in and a push. |
| Migrations on deploy | Done: run at container start. Verified locally. |
| Safe demo seed | Done: production seeding needs `SEED_DEMO_DATA` and `SEED_PASSWORD`; the published local password is refused there. Verified locally. |
| One Playwright journey (sign in, create listing, search) | Done, plus submit for review, withdraw, archive, sign out. Passed locally against the image. |

Checks run locally: API `ruff format --check`, `ruff check`, `mypy` (strict), `pytest` (59 passed); web `eslint`, `prettier --check`, `tsc --noEmit`, `vitest` (31 passed), `vite build`; `docker build`; container run with `PORT=10000` and a `postgres://` URL; `pnpm e2e` against the container (1 passed).

## Not verified

- `render.yaml` has not been read by Render.
- GitHub Actions has never run for this project: `api`, `web` and `e2e` jobs are untested there. `actions/*` versions and the `pnpm/action-setup` input name are the likeliest things to need a fix.
- Nothing has been checked on a real `.onrender.com` URL.

## Known limitations

See "Known limits of this demo deployment" in `docs/deployment/render.md`. In addition:

- The image installs Python dependencies from version ranges, not a lock file, so two builds can differ.
- No security headers (CSP, HSTS) are set by the app (Sprint 21).
- The end-to-end test needs seeded demo data and leaves one archived listing per run.

## Next

Chunk 4 (go live), then the Phase A gate: developer feedback before Phase B (Sprint 6, media and job system).
