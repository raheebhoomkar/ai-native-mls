# The API alone, for the Vercel "api" service (see vercel.json). Build context: services/api.
# The repository-root Dockerfile is the Render image, which also serves the built web app.

# Wheels are built here, where a C compiler is available: some dependencies (zstandard,
# pulled in by LangGraph) have no prebuilt wheel for this Python yet.
FROM python:3.15-slim AS wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/services/api
COPY pyproject.toml ./
COPY app ./app
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.15-slim
# RUN_WORKER=false: instances sleep between requests, so jobs run through GET
# /api/v1/ops/run-jobs (Vercel Cron) or a daemon. FORWARDED_ALLOW_IPS: only Vercel's proxy
# reaches the container, so its X-Forwarded-For (the client's address) is trusted.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    RUN_WORKER=false \
    FORWARDED_ALLOW_IPS=*
# Same relative layout as the repository, which app/core/config.py relies on.
WORKDIR /srv/services/api
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/*.whl && rm -rf /wheels
COPY alembic.ini start.sh ./
COPY app ./app
COPY migrations ./migrations
RUN useradd --system --no-create-home app
USER app
EXPOSE 8000
CMD ["./start.sh"]
