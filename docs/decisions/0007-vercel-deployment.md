# ADR 0007: Deploying on Vercel

- **Date:** 2026-11-17
- **Status:** Accepted. Supersedes ADR 0002 for the hosted demo; the Render files stay and still work.

## Context

The developer chose Vercel for the hosted app. The app has three parts: a Vite web app (static files), a FastAPI API (Python 3.15, OpenCV, LangGraph), and a background job worker (`python -m app.worker`) that polls the Postgres job queue (ADR 0003) for thumbnails, AI runs, redaction, geocoding, search indexing, webhooks and workflows.

Vercel runs code per request and lets instances sleep. An always-running worker needs a Vercel daemon, which is a separate, billed feature. Vercel Cron on the Hobby plan runs at most once a day.

## Options considered

1. FastAPI on Vercel's native Python runtime. Depends on Vercel supporting Python 3.15 and on OpenCV fitting a function bundle; neither is verified.
2. The API as a **container service** built from `services/api/Dockerfile`. Same image as local and Render, so Python 3.15 and OpenCV work.
3. Static web app served by the API (as on Render). Static files would go through Python instead of Vercel's CDN.
4. Jobs: (a) a daemon running the worker; (b) an HTTP route that runs due jobs, called by a scheduler; (c) run jobs inside each request. Option (c) would make uploads and AI requests wait 15 to 40 seconds.

## Decision

- One Vercel project with **Vercel Services** (`vercel.json`): `web` (Vite build on the CDN, SPA fallback to `index.html`) and `api` (container, option 2). Public routes: `/api/*` to `api`, everything else to `web`. One origin, so the `SameSite=Lax` session cookie and relative `/api` calls work unchanged, with no CORS.
- Jobs through **`GET /api/v1/ops/run-jobs`** (option 4b). It needs `Authorization: Bearer <CRON_SECRET>`, queues the daily cleanup when due, and runs due jobs for up to 50 seconds. Without `CRON_SECRET` it answers 404. Vercel Cron calls it (it sends that header itself). On Hobby the cron runs once a day, so the guide adds a free external scheduler calling it every minute. Where daemons are available, a daemon running `python -m app.worker` replaces both (option 4a).
- The container runs `start.sh` with `RUN_WORKER=false`: migrations and the optional demo seed run at start-up under one Postgres advisory lock (`STARTUP_LOCK`), so instances starting together do not race.
- Media in an S3-compatible bucket (`MEDIA_STORAGE=s3`); a container's disk is neither shared nor kept.

## Trade-offs

- With a scheduler every minute, a photo thumbnail, AI suggestion or workflow step can take up to a minute to start, instead of a few seconds with a worker.
- A job cut off by a request timeout is retried after its 15-minute lease (ADR 0003); a 50-second budget keeps that rare.
- Migrations at start-up add a second or two to a cold start, and every cold start after a deploy checks the schema.
- The container service, Services and daemons are newer Vercel features; `vercel.json` is not validated until Vercel reads it.
