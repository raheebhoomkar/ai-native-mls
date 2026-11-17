#!/bin/sh
# Container entry point: migrate, seed demo data if configured, then serve.
set -e

alembic upgrade head
python -m app.seed --if-configured

# The background job worker runs beside the web server in this one container (Render).
# shortcut: a crashed worker is not restarted until the container restarts; give it its own
# Render worker service (paid plans) when that matters. Unfinished jobs are reclaimed.
# RUN_WORKER=false where instances sleep between requests (Vercel): a scheduler calls
# GET /api/v1/ops/run-jobs instead, or the worker runs as its own daemon.
if [ "${RUN_WORKER:-true}" = "true" ]; then
  python -m app.worker &
fi

# FORWARDED_ALLOW_IPS: addresses of the reverse proxy whose X-Forwarded-* headers are trusted.
# The default trusts none but localhost, so a client cannot fake its IP address.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
