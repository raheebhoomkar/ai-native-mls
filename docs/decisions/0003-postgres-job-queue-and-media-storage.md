# ADR 0003: Background jobs in Postgres; media behind a storage interface

- **Date:** 2026-11-17
- **Status:** Accepted.

## Context

Sprint 6 (Module 3) needs work that runs after a request: thumbnails now, and AI extraction, re-indexing, webhooks and notifications in later sprints. It also needs somewhere to keep uploaded files that works the same on a laptop, in tests and on a host.

The demo runs as one container with one Postgres database on a free plan (ADR 0002). Adding a broker such as Redis or RabbitMQ means another service to run, pay for and keep consistent with the database.

## Decision

**Jobs.** A `jobs` table in the existing Postgres database. A job is inserted in the same transaction as the change that needs it. Workers (`python -m app.worker`) claim one due job at a time with `SELECT … FOR UPDATE SKIP LOCKED`, so several workers never take the same job. Failed attempts are retried with doubling backoff (30 s, 60 s, …) up to `max_attempts`, then marked failed and passed to an optional `on_failed` hook. A job left `running` past a 15-minute lease, because its worker died, is taken over. Handlers must be safe to run twice. On the demo, the worker runs in the same container as the web server, started by `start.sh`.

**Media.** A small `Storage` interface (`put`, `get`, `delete`) with a local-disk adapter (development, tests, a single server) and an S3-compatible adapter (AWS S3, Cloudflare R2, MinIO), chosen by `MEDIA_STORAGE`. Files are served by the API through short-lived HMAC-signed URLs, so permission checks stay in one place and the bucket stays private. Originals are never changed; thumbnails are separate rows and files. Removed media is hidden at once and its files are deleted by a job after `MEDIA_RETENTION_DAYS`.

## Why

- No new infrastructure. Jobs share the database's backups and transactions: a job exists if and only if the change that queued it committed, with no outbox or two-phase commit needed.
- `SKIP LOCKED` is a standard Postgres pattern and is fast enough for the expected volume (thousands of jobs a day, not millions).
- One interface means the same upload, thumbnail and retention code runs against local disk in tests and against a bucket in production.

## Trade-offs and when to revisit

- Workers poll every 2 seconds, so a job can wait that long before it starts. Move to `LISTEN/NOTIFY` or a broker if lower latency is needed.
- Throughput is bounded by the database. Revisit if jobs reach hundreds per second or start to slow down request traffic.
- On the demo, a crashed worker is not restarted until the container restarts. Run it as its own service when the host allows.
- Serving files through the API costs API bandwidth and memory (files up to `MEDIA_MAX_BYTES`, read whole). Revisit with redirects to presigned bucket URLs, or a CDN, if photo traffic grows.
- Local disk on Render's free plan is wiped on every deploy; the demo needs a bucket for uploads to last.
