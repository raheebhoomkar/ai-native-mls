#!/bin/sh
# Container entry point: migrate, seed demo data if configured, then serve.
set -e

alembic upgrade head
python -m app.seed --if-configured

# FORWARDED_ALLOW_IPS: addresses of the reverse proxy whose X-Forwarded-* headers are trusted.
# The default trusts none but localhost, so a client cannot fake its IP address.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
