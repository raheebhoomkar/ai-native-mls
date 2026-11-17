# One image: the API, which also serves the built web app. Build from the repository root.

FROM node:24-slim AS web
WORKDIR /src/apps/web
RUN npm install --global pnpm@12.18.0
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web ./
RUN pnpm build

# Wheels are built here, where a C compiler is available: some dependencies (zstandard,
# pulled in by LangGraph) have no prebuilt wheel for this Python yet. The final image stays
# without a compiler.
FROM python:3.15-slim AS wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/services/api
COPY services/api/pyproject.toml ./
COPY services/api/app ./app
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.15-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    WEB_DIST_DIR=/srv/web
# Same relative layout as the repository, which app/core/config.py relies on.
WORKDIR /srv/services/api
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/*.whl && rm -rf /wheels
COPY services/api ./
COPY --from=web /src/apps/web/dist /srv/web
RUN useradd --system --no-create-home app \
    && mkdir -p /srv/var/media && chown app /srv/var/media
USER app
EXPOSE 8000
CMD ["./start.sh"]
