# Operations runbooks

What to check, what to do when something breaks, how to back up and restore, and how long data is kept. Written for the demo deployment (`render.yaml`, one container running the API, the web app and the worker, plus one Postgres) and for local runs. Commands run from the repository root unless a step says otherwise.

## 1. Monitoring

| What | Where to look | Healthy |
|---|---|---|
| API and database | `GET /api/v1/health` (Render's health check uses it) | `{"status": "ok", "database": "ok"}`; HTTP 503 `database_unavailable` when Postgres is unreachable |
| Background jobs, webhooks, AI | Platform page > **Service health**, or `GET /api/v1/ops/status` as a platform administrator | "No problems found." |
| One organisation's jobs | Monitor page (administrators), with Retry on failed jobs | No failed jobs |
| One organisation's webhooks | Webhooks page > **Failed deliveries**, with Send again | "No failed deliveries." |
| Logs | Render dashboard > service > Logs, or the terminal locally. One JSON object per line, each with `request_id` | No lines with an `alert` field |

**Alerts in the logs.** Lines that need a person carry an `alert` field. Search the logs for `"alert"`:

- `"alert": "unknown_job_kind"`: a worker found a job it has no handler for. Usually the API and the worker run different versions of the code. The job fails at once.
- `"alert": "job_failed"`: a job used up all its attempts. The `kind` field says which.

There is no paging or email. To be told without looking, add a Render log stream (or any log drain) to a log service and alert on `"alert"`, and point an uptime checker at `/api/v1/health`.

**What Service health reports** (last 24 hours unless said otherwise): queued jobs and how many have waited over 5 minutes (a stopped worker), running jobs, failed jobs, failed jobs that belong to no organisation (no Monitor page shows those), job kinds no handler runs, webhook deliveries being tried and failed, failed AI extraction runs with the last error.

## 2. Incident response

1. **Confirm.** Open `/api/v1/health` and the Platform page's Service health. Note the time and any request ID from the error the user saw (the web app adds "(request …)" to server errors and sign-in failures; every log line has `request_id`).
2. **Contain.** If a change caused it, redeploy the previous commit (Render > service > Events > the last good deploy > Rollback). Migrations are additive, so the previous code runs on the newer schema.
3. **Find the cause.** Search the logs for the `request_id`, or for `"alert"`. A job's `trace_id` (Monitor page) is the `request_id` of the request that queued it.
4. **Fix**, then use the matching recipe in section 3.
5. **Write it down.** What happened, when, who was affected, the cause, what was changed, and what stops it happening again. Keep the note with the team's other incident notes.
6. **Personal data.** If personal data may have been seen by someone who should not have seen it, tell the project lead the same day. They decide who else must be told.

## 3. Recipes

### Database unreachable (`/health` answers 503)

Check the database in the Render dashboard (status, connection limit, storage). Locally: `docker compose ps` and `docker compose up -d --wait`. The API reconnects by itself; no restart is needed once the database is back.

### Jobs are not running (Service health: "have waited over 5 minutes")

The worker runs beside the web server (`services/api/start.sh`). A crashed worker is not restarted until the container restarts: restart the service (Render > Manual Deploy > Restart service). Locally, start `python -m app.worker` again. Jobs that were running when the worker died are taken over after 15 minutes. On Render's free plan the service sleeps when idle, and no jobs run while it sleeps.

### Unknown job kind

Make the API and the worker run the same commit (on Render they are one container, so redeploy). Then retry the failed jobs from the Monitor page. A job kind that was removed on purpose leaves failed jobs behind; they do no harm and the daily cleanup does not remove them.

### A job failed for good (dead letter)

Read `last_error` on the Monitor page. Fix the cause (for example a missing file or an AI provider outage), then press Retry: the job gets a fresh set of attempts. Platform jobs (no organisation) have no Retry button; today the only one is the daily cleanup, which runs again the next day by itself.

### Webhook deliveries failed (dead letters)

Each delivery is tried 6 times over about 15 minutes, then kept as failed. On the Webhooks page, under Failed deliveries, read the last answer, ask the receiver to fix their endpoint, then press Send again (same body, same event ID, fresh attempts). The receiver should ignore an event ID it has already processed.

### AI provider failures

Service health shows the count and the last error. `ProviderUnavailable` or HTTP 429/503 from Gemini is usually a free-tier limit or a busy model: wait and run the extraction again from the listing. Without `GEMINI_API_KEY` the app uses the labelled demo provider and makes no outside calls.

### Slow API

Run the load smoke test (section 5) against the same server and compare with the last result. Check the database's CPU and connections in the Render dashboard.

## 4. Backup and restore

The scripts use `pg_dump` and `pg_restore` from your PATH, or from the `postgres` container of `docker-compose.yml` when they are not installed. Set `PG_RUN` to run them some other way (CI uses `docker run --rm -i --network host postgres:17`). Use Postgres 17 tools: older ones refuse a Postgres 17 server.

**Back up:**

```bash
DATABASE_URL='postgresql://user:password@host:5432/mls' scripts/backup.sh
# prints var/backups/mls-<UTC time>.dump (var/ is not committed)
```

For Render, use the database's **External Database URL** (dashboard > `mls-db` > Connect). Keep backups out of the repository and away from shared drives: they contain everything, including password hashes and personal data.

**Restore** (replaces the tables in the target database; the target must exist):

```bash
scripts/restore.sh var/backups/mls-<time>.dump 'postgresql://user:password@host:5432/mls_restored'
```

Restore into a new database first, check it, then point the app at it (`DATABASE_URL`) rather than overwriting the live database. Uploaded photos are files, not database rows: back up the storage too (the local `var/media` folder, or the S3 bucket when `MEDIA_STORAGE=s3`).

**Tested restore.** `scripts/backup_restore_check.sh` backs up `DATABASE_URL`, restores into `<name>_restore_check` on the same server, compares the row count of every table, and drops the scratch database. CI runs it on every pull request after the browser journeys, against the database they just used. Run it by hand before relying on a new backup routine.

**Render free plan:** the free database has no backups of its own and is deleted after a limited period. Take a backup before anything you want to keep, such as a demo for the company.

## 5. Load smoke test

```bash
python3 scripts/load_smoke.py --base-url http://localhost:8000 \
  --email sunrise.agent@demo.example.com --password local-dev-password
```

Ten clients share one sign-in and read listings, health and the dashboard for 20 seconds. It prints requests, errors and p50/p95 latency, and exits 1 when errors are over 1 % or p95 is over 1000 ms (`--clients`, `--seconds`, `--max-p95-ms`, `--max-error-rate` change these). It is a smoke test, not a capacity test. Result on a laptop on 2026-11-17: 5358 requests in 10 s, 0 errors, p95 27 ms. A sleeping Render free service takes up to a minute to wake: run it twice and read the second result.

## 6. Dependency scanning

- CI job `audit` on every pull request: `pip-audit` over the API's installed packages, `pnpm audit --prod` over the web app's runtime packages. It fails on any known vulnerability.
- Dependabot (`.github/dependabot.yml`) opens weekly pull requests for pip, npm, GitHub Actions and Docker base images. CI runs on each.
- A finding with no fixed version yet: record it in the pull request, and add an ignore only with a reason and a date to look again.

## 7. Data retention

| Data | Kept for | Removed by |
|---|---|---|
| Idempotency records (stored answers to retried writes) | 24 hours | Daily cleanup job (`ops.cleanup`) |
| API key usage log | 90 days | Daily cleanup job |
| Succeeded background jobs | 30 days | Daily cleanup job |
| Failed background jobs | Until deleted by hand | Kept as dead letters |
| Webhook deliveries | Indefinitely | Not cleaned up yet; failed ones are the dead letters |
| Audit log | Indefinitely | Never deleted by the app |
| Listings, photos, comments, notifications | Until a person deletes or archives them | Removed photos' files are deleted by a job |
| Sign-in sessions | Until they expire (`SESSION_TTL_HOURS`, 12 by default) or sign-out | Expired sessions are refused; rows are not deleted yet |

The worker queues the cleanup once a day (it checks every hour, and a Postgres advisory lock stops two workers both queuing it). Change the periods in `services/api/app/modules/ops/service.py`. These periods are engineering defaults for the demo, not legal advice; the company sets the real ones.

## 8. Reproducing the deployment

Everything the demo needs is in the repository: `Dockerfile` (one image: API, built web app, worker), `services/api/start.sh` (migrations, optional demo seed, worker, server), `render.yaml` (service, database, environment variables) and `.env.example` (every setting, with what it does). Secrets are generated by Render (`SEED_PASSWORD`, `MEDIA_SIGNING_KEY`) or added in its dashboard (`GEMINI_API_KEY`); none are in the repository. Steps: `docs/deployment/render.md`. Infrastructure that is planned but not used, and when to add it: `docs/decisions/0006-deferred-infrastructure.md`.
