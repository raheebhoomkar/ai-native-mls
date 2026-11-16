# One image: the API, which also serves the built web app. Build from the repository root.

FROM node:24-slim AS web
WORKDIR /src/apps/web
RUN npm install --global pnpm@12.18.0
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web ./
RUN pnpm build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    WEB_DIST_DIR=/srv/web
# Same relative layout as the repository, which app/core/config.py relies on.
WORKDIR /srv/services/api
COPY services/api/pyproject.toml ./
COPY services/api/app ./app
RUN pip install --no-cache-dir .
COPY services/api ./
COPY --from=web /src/apps/web/dist /srv/web
RUN useradd --system --no-create-home app
USER app
EXPOSE 8000
CMD ["./start.sh"]
