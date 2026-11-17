# Deploying to Vercel

One Vercel project with two services, described by `vercel.json` at the repository root (decision: `docs/decisions/0007-vercel-deployment.md`):

| Service | Built from | Serves |
|---|---|---|
| `web` | `apps/web` (Vite) | Every path except `/api/*`, from Vercel's CDN. Unknown paths get `index.html`, so deep links work. |
| `api` | `services/api/Dockerfile` (container) | `/api/*`. Runs migrations and the optional demo seed when an instance starts. |

Both are on one origin, so the session cookie and the web app's relative `/api` calls work as they do locally.

You also need a Postgres database (Neon, from the Vercel Marketplace) and an S3-compatible bucket for photos (Cloudflare R2's free tier is enough). Background jobs run through a protected URL that a scheduler calls; see [Background jobs](#background-jobs).

**Status: not deployed yet.** The API image has been built and run locally as Vercel runs it (`RUN_WORKER=false`, `postgres://` URL, migrations and seed at start, the job route called with the secret). `vercel.json` has not been read by Vercel yet, so the first deployment is its first real test.

Sign in to Vercel, Neon, Cloudflare and Google yourself. Never put passwords, keys or secrets in chat, in the repository or in `vercel.json`.

## 1. Before you start

- The code on GitHub, on the branch you will deploy (normally `main`), with CI green.
- A Vercel account that can read the repository.
- Python 3 on your laptop, only to generate secrets (step 4).

## 2. Create the project

1. Vercel dashboard, **Add New > Project**, import this repository.
2. Leave **Root Directory** as the repository root and **Framework Preset** as detected. Vercel reads `vercel.json` and shows the `web` and `api` services.
3. Do not deploy yet if Vercel offers to; the environment variables come first. (If it deploys anyway, the API fails to start until step 4 is done. That is harmless; redeploy afterwards.)

## 3. Database and photo storage

**Postgres (Neon).** Project > **Storage > Create Database > Neon** (Marketplace), pick the region closest to your users (the same region as the project's functions, see Settings > Functions), connect it to this project for Production and Preview. Vercel adds `DATABASE_URL` and related variables. The app accepts Neon's `postgres://...?sslmode=require` URL as it is.

**Photos (Cloudflare R2).** In Cloudflare: **R2 > Create bucket** (private, for example `mls-media`), then **Manage R2 API tokens > Create API token** with "Object Read & Write" on that bucket. Note the access key ID, the secret access key and the S3 endpoint (`https://<account-id>.r2.cloudflarestorage.com`). AWS S3 works too; leave `MEDIA_S3_ENDPOINT_URL` unset for AWS.

## 4. Environment variables

Generate three secrets on your laptop:

```bash
python3 -c "import secrets; print('MEDIA_SIGNING_KEY', secrets.token_urlsafe(48)); print('CRON_SECRET', secrets.token_urlsafe(32)); print('SEED_PASSWORD', secrets.token_urlsafe(12))"
```

Project > **Settings > Environment Variables**, for Production (and Preview if you use previews):

| Variable | Value | Purpose |
|---|---|---|
| `DATABASE_URL` | added by Neon | Postgres. |
| `MEDIA_SIGNING_KEY` | generated | Signs short-lived photo links. The API refuses to start without it. |
| `CRON_SECRET` | generated | Protects `GET /api/v1/ops/run-jobs`. Vercel Cron sends it automatically. |
| `SEED_DEMO_DATA` | `true` | Creates the demo organisations, accounts and `[Demo]` listings at start-up if missing. Set `false` once you no longer want them. |
| `SEED_PASSWORD` | generated | Password of every demo account. Changing it later does not change accounts already created. |
| `MEDIA_STORAGE` | `s3` | Photos in the bucket. Without it photos are lost when an instance stops. |
| `MEDIA_S3_BUCKET` | `mls-media` | Bucket name. |
| `MEDIA_S3_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` | R2 endpoint (unset for AWS). |
| `MEDIA_S3_REGION` | `auto` | `auto` for R2; the bucket's region for AWS. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | from the R2 token | Bucket credentials (the names are standard even for R2). |
| `MEDIA_MAX_BYTES` | `4194304` | 4 MB. Vercel refuses request bodies over 4.5 MB, so larger photos would fail with a platform error instead of the app's message. |

Optional:

| Variable | Value | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | from https://aistudio.google.com/apikey | Real AI for photo suggestions, redaction and the policy check. Without it the labelled `[Demo]` provider is used. The free tier may use what you send to train Google's models: demo photos only. |
| `EMBEDDER` | `gemini` | Semantic search by meaning (needs the key). After switching, run a re-index (step 8). |
| `GEOCODER`, `GEOCODER_USER_AGENT` | `nominatim`, `ai-native-mls (you@example.com)` | Real geocoding through OpenStreetMap Nominatim, 1 request per second. |

`ENVIRONMENT=production`, `RUN_WORKER=false` and `FORWARDED_ALLOW_IPS=*` are set in `services/api/Dockerfile`; do not set them here.

## 5. Deploy

Project > **Deployments > Redeploy** (or push to the branch). The first build takes several minutes (the API image compiles some Python wheels).

The first request to the API starts an instance, which runs the migrations and creates the demo data before it answers; expect that first request to take up to about 30 seconds. If it times out, reload.

## 6. Check it

```bash
APP=https://<your-project>.vercel.app
curl -s $APP/api/v1/health                 # {"status":"ok","database":"ok"}
curl -s -H "Authorization: Bearer <CRON_SECRET>" $APP/api/v1/ops/run-jobs   # {"ran":<n>}
```

Then open `$APP`, sign in as `sunrise.agent@demo.example.com` with the `SEED_PASSWORD` value, and follow `docs/DEMO.md`. The accounts are listed there.

Browser test against the live site, from `apps/web` (it creates one listing and archives it again; the workflow test needs the every-minute job runner from the next section):

```bash
E2E_BASE_URL=$APP E2E_PASSWORD='<SEED_PASSWORD>' pnpm e2e
```

## Background jobs

Thumbnails, AI suggestions, redaction, policy checks, geocoding, search indexing, webhooks, workflow steps and the daily cleanup are jobs in the Postgres queue. On Vercel nothing runs them until `GET /api/v1/ops/run-jobs` is called with the secret; each call runs due jobs for up to 50 seconds. Choose one:

- **Pro plan:** in `vercel.json` change the cron `schedule` from `0 3 * * *` (daily, the most Hobby allows) to `* * * * *` (every minute) and redeploy. Jobs then start within a minute.
- **Hobby plan:** keep the daily cron (it runs the cleanup) and add a free external scheduler. For example at https://cron-job.org: new job, URL `https://<your-project>.vercel.app/api/v1/ops/run-jobs`, every minute, request header `Authorization: Bearer <CRON_SECRET>`. Keep the secret in that service only.
- **Vercel daemon** (if your plan offers daemons): an always-running worker, so jobs start within seconds. Add to `vercel.json` and redeploy:

  ```json
  "daemons": {
    "worker": {
      "root": "services/api",
      "entrypoint": "Dockerfile",
      "command": ["python", "-m", "app.worker"],
      "instances": { "iad1": 1 },
      "terminationGracePeriodSeconds": 120
    }
  }
  ```

  Use the region of your functions instead of `iad1`. The cron can stay; it then finds nothing to do.

Without any of these, photos stay "Processing" and AI runs stay queued. The Platform page's "Service health" (as `platform.admin@demo.example.com`) says "Background jobs waiting over 5 minutes" when the runner is not being called.

## 7. Later deployments

Every push to the production branch builds and deploys both services together. Migrations run when the first new instance starts, under a database lock, so two instances never migrate at once. The seed skips what already exists.

## 8. Recipes

Run a command against the hosted database from your laptop (for example a re-index after `EMBEDDER=gemini`, or migrations by hand). Copy `DATABASE_URL` and, for anything that touches photos, the `MEDIA_*` and `AWS_*` values from the dashboard into your shell, never into a file in the repository:

```bash
cd services/api
DATABASE_URL='<from Vercel>' ENVIRONMENT=production MEDIA_SIGNING_KEY='<from Vercel>' \
  .venv/bin/python -m app.modules.search.cli reindex
```

Backups: `scripts/backup.sh` with `DATABASE_URL` set to the Neon URL (`docs/operations/runbooks.md`). Neon also keeps its own point-in-time history for a limited period, depending on the plan.

## 9. Rollback

Project > **Deployments**, pick the last good deployment > **Instant Rollback**. Both services roll back together. This rolls back code only: migrations so far only add tables and columns, so older code works against a newer database. A migration that changes or drops something needs its own rollback note.

## Known limits of this deployment

- With a scheduler every minute, jobs start up to a minute late; with the daily cron alone, once a day.
- A job cut off by the 50-second budget or a request timeout is retried after its 15-minute lease.
- Photos are limited to 4 MB (Vercel's request body limit).
- `FORWARDED_ALLOW_IPS=*` trusts the forwarded client address. That is fine only because the container is reachable solely through Vercel's proxy; the sign-in rate limit per IP address depends on it.
- No alerts by email or paging: add a log drain (Project > Settings > Log Drains) and an uptime check on `/api/v1/health`.
- Demo accounts share one password, including the demo platform administrator. Share it only with reviewers; put no real data in the demo.
- The PWA install and offline start were checked against the production build served locally, not on Vercel.

## Running the API image locally

```bash
docker compose up -d --wait
docker build -t mls-api-vercel services/api
docker run --rm -p 127.0.0.1:8000:8000 --network ai-native-mls_default \
  -e DATABASE_URL=postgres://mls:mls@postgres:5432/mls \
  -e MEDIA_SIGNING_KEY=local-signing-key-at-least-32-characters \
  -e CRON_SECRET=local-cron-secret-123 \
  mls-api-vercel
curl -s -H "Authorization: Bearer local-cron-secret-123" http://localhost:8000/api/v1/ops/run-jobs
```

This uses your local development database and its seed accounts. The web app is not in this image; use `pnpm dev` in `apps/web` (it proxies `/api` to port 8000).
