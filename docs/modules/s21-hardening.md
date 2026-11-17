# Sprint 21: Hardening (Module 14)

**Status: done (2026-11-17).** Second sprint of Phase D. Nothing committed.

Branch: `feature/s6-media-jobs`. Nothing is committed by Claude; the developer commits.

Scope (from the approved plan): backup and tested restore, monitoring of API/DB/jobs/AI failures, dependency scanning, load smoke test, dead-letter handling for jobs and webhooks, runbooks, ADR on deferred infrastructure. The Phase C report adds: cleanup jobs for idempotency records and old usage rows, a dead-letter view for webhook deliveries, and an alert when a worker meets an unknown job kind.

## How to resume

1. `git status` and `git log --oneline | head -3` to see what is committed and what is staged.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Find the first unchecked chunk below. Do only that chunk.
4. Run the checks under "Checks", tick the chunk, add a line under "Log", stage.

## Design decisions (reversible; made 2026-11-17)

- **Ops module** `app/modules/ops/` (no tables). `GET /api/v1/ops/status`, platform administrators only: database, jobs (queued, overdue, running, failed in the last 24 hours, failed platform jobs, unknown kinds), webhook deliveries (pending, failed in the last 24 hours) and AI runs (failed in the last 24 hours, last error), plus a list of alerts in plain words. `/api/v1/health` stays as it is for the host's health check.
- **Alerts in logs.** Problems an operator must see are logged at ERROR with an `alert` field (`unknown_job_kind`, `job_failed`), so a log drain or the host's log search can alert on them. No email or paging service.
- **Cleanup.** Platform job `ops.cleanup`: deletes idempotency records past their 24-hour life, API key usage rows older than 90 days, and succeeded jobs older than 30 days. Failed jobs and webhook deliveries are kept, since they are the dead letters. The worker makes sure one is scheduled per day (Postgres advisory lock, so two workers do not both queue it).
- **Dead letters.** Jobs: a job that fails all its attempts stays `failed`, visible on Monitor with Retry (already built). Webhooks: `GET /api/v1/webhooks/deliveries/failed` lists failed deliveries across the organisation's webhooks; the Webhooks page shows them with Redeliver.
- **Backup and restore.** `scripts/backup.sh` (`pg_dump --format=custom`) and `scripts/restore.sh` (`pg_restore` into a named database). `scripts/backup_restore_check.sh` backs up, restores into a scratch database and compares row counts of every table; CI runs it.
- **Dependency scanning.** CI job `audit`: `pip-audit` on the API's installed packages and `pnpm audit --prod` on the web app. `.github/dependabot.yml` for pip, npm and GitHub Actions, weekly.
- **Load smoke test.** `scripts/load_smoke.py`, standard library only: N concurrent clients sign in and read listings and health for a set time, then print request count, error count and p50/p95 latency, and exit non-zero over the limits.

## Chunks

- [x] **1. Backend.** Ops module and route, unknown-kind and final-failure alerts in the job runner, cleanup job and daily scheduling in the worker, failed-deliveries route, tests, `pnpm gen:api`.
- [x] **2. Screens.** Platform page shows the ops status and its alerts; Webhooks page shows failed deliveries with Redeliver. Tests.
- [x] **3. Scripts and CI.** Backup, restore, restore check, load smoke test, CI `audit` job and restore check, Dependabot.
- [x] **4. Docs.** Runbooks (incident response, restore, data retention, monitoring), ADR 0006 on deferred infrastructure, HOW_TO_RUN, this note.

## Conventions to follow (already in the codebase)

- API calls: `api()`, `useAction()`, `useList()` in `apps/web/src/api.ts`.
- Show or hide by `my_permissions`, never by role name. Every control works.
- Types from `apps/web/src/api-schema.d.ts` (`pnpm gen:api` after an API change).
- Module layout `services/api/app/modules/<name>/{router,schemas,service}.py`; another module's data only through its `service`.
- Platform administrator check: `PlatformAdmin` in `app/modules/auth/deps.py`.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/alembic check && .venv/bin/pytest -q
# from apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk: date, what was done, anything left open)
- 2026-11-17, chunk 1 done. `app/modules/ops/` (`GET /ops/status`, `ops.cleanup` job, `ensure_cleanup_scheduled`), worker checks hourly; `jobs.service` alerts (`unknown_job_kind`, `job_failed`) and `counts`, `unknown_kinds`, `exists_since`, `delete_succeeded_before`; `webhooks.service.list_failed_deliveries`, `counts`; `apikeys.service.delete_expired`; `ai.service.failures_since`; `GET /webhooks/deliveries/failed`. `tests/test_ops.py` (5). API: 341 passed, ruff, mypy, alembic check clean. `pnpm gen:api` run. Worker run by hand: queued and ran the cleanup.
- 2026-11-17, chunk 2 done. `OpsStatus.tsx` ("Service health": alerts, job, webhook and AI numbers, "Check again") at the top of the Platform page; Webhooks page "Failed deliveries" table across webhooks with a Webhook column and "Send again" (`Deliveries` now takes `path`, `caption`, `empty`, `urls`). `OpsStatus.test.tsx` (2), 2 more in `Webhooks.test.tsx`. Web: 90 tests, lint, typecheck, build.
- 2026-11-17, chunk 3 done. `scripts/pg.sh`, `backup.sh`, `restore.sh`, `backup_restore_check.sh` (local run: 33 tables, same row counts), `load_smoke.py` (local run: 5358 requests in 10 s from 10 clients, 0 errors, p95 27 ms). CI: `audit` job (`pip-audit --skip-editable`, `pnpm audit --prod`; both clean locally) and a backup-and-restore step after the e2e journeys. `.github/dependabot.yml` (pip, npm, Actions, Docker; weekly).
- 2026-11-17, chunk 4 done. `docs/operations/runbooks.md` (monitoring, incident response, recipes, backup and restore, load smoke, dependency scanning, data retention, reproducing the deployment), `docs/decisions/0006-deferred-infrastructure.md`, HOW_TO_RUN (table row, operations checks, walkthrough 6.16). Alerts reworded as "<what>: <count>" so one item reads right. Playwright against the dev server: 9 passed, 1 skipped (production only). Platform and Webhooks pages checked at 390 px: no sideways scrolling.

## Acceptance results (INSTRUCTIONS.md Module 14)

- **Each extra component has a use case and operational plan:** ADR 0006 lists Kafka, Debezium, Temporal, Flink, TimescaleDB, Neo4j and Kong as deferred, what does each job today, the trigger for adding it, and what any addition must ship with. None is deployed.
- **Events are not silently lost; retries and dead letters exist:** events go through the transactional outbox (S13/S18). Jobs retry with backoff and stay `failed` with Retry on Monitor (`test_jobs.py`). Webhook deliveries retry 6 times and stay `failed`; the new failed-deliveries list shows them across webhooks with Send again (`test_failed_deliveries_list_is_per_organisation`, `Webhooks.test.tsx`). An unknown job kind fails at once and logs an alert (`test_unknown_job_kind_fails_at_once_with_an_alert`).
- **Backups and restore are tested:** `scripts/backup_restore_check.sh` restores into a scratch database and compares every table's row count; it passes locally and runs in CI after the browser journeys.
- **Monitoring covers API, database, jobs and AI failures:** `/api/v1/health` (API and database), `GET /api/v1/ops/status` and the Platform page's Service health (jobs, overdue jobs, unknown kinds, webhook and AI failures, with plain-word alerts), and `alert` fields in the logs (`test_ops_status_is_for_platform_admins_and_names_problems`, `OpsStatus.test.tsx`).
- **Deployment reproducible from documented configuration:** runbooks section 8 lists the files; secrets live only in the host.
- **Load and security testing, dependency scanning:** `scripts/load_smoke.py` (local: 0 errors, p95 27 ms); CI `audit` job (`pip-audit`, `pnpm audit --prod`, both clean on 2026-11-17); Dependabot weekly.
- **Data retention, incident response, runbooks:** `docs/operations/runbooks.md`.
- All checks pass: API ruff, mypy, alembic check, pytest (341); web lint, typecheck, test (90), build; Playwright 9 passed, 1 skipped (dev server).

## Known limitations

- No paging or email alerts: alerts are log fields and a page. A log drain and an uptime checker must be set up on the host to be told without looking.
- The new CI steps (`audit` job, backup-and-restore step) have not run on GitHub yet; nothing has been pushed. The same commands pass locally.
- Backups are by hand (`scripts/backup.sh`); there is no schedule. Render's free Postgres has no backups of its own. Uploaded photo files are not in the database backup.
- The load smoke test is light (10 clients, one user, reads only) and ran on a laptop, not on Render.
- No security scan beyond dependency audits (no DAST, no container image scan).
- Webhook deliveries and sign-in session rows are never deleted. Failed jobs stay until deleted by hand.
- Service health counts AI extraction runs only; redaction and policy-check AI failures show up as failed jobs.
- The worker still runs inside the web container on Render (from S5); a crashed worker waits for a container restart. Service health now shows it as overdue jobs.
- The S5 go-live (push and Render Blueprint) is still open, so nothing here has run on a live URL.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Platform-wide health numbers | `ops.service.status`; add a new component's health there |
| Something an operator must see | `logger.error(..., extra={"alert": "<name>", ...})` |
| Retention | `ops.service.cleanup` and the `KEEP_*` periods beside it |
| Counts for monitoring | `jobs.service.counts`, `jobs.service.unknown_kinds`, `webhooks.service.counts`, `ai.service.failures_since` |
| Backups | `scripts/backup.sh`, `scripts/restore.sh`, `scripts/backup_restore_check.sh` (set `PG_RUN` to run Postgres tools another way) |

## Next

S21 is complete. Stop for the developer's feedback before S22 (handover): demo script, architecture diagram, ERD, agent workflow diagram, known limitations, release tag, transfer checklist. The S5 go-live (push and Render Blueprint) is still open; S22's demo needs it.
