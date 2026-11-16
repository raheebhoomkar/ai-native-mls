# AI-Native MLS

An API-first, AI-assisted Multiple Listing Service for real-estate professionals. The full product definition and module roadmap are in [INSTRUCTIONS.md](INSTRUCTIONS.md).

**Status:** Sprint 0 (Module 0, foundation) is complete. The repository contains a running API with a health endpoint, a web shell that shows system status, local Postgres, and CI. Authentication, listings, media and AI features are not built yet. There is no live demo URL yet.

## Layout

| Path | Contents |
|---|---|
| `services/api` | FastAPI modular monolith. Shared code in `app/core`, one directory per feature in `app/modules`. |
| `apps/web` | React + Vite web app (responsive; PWA planned). |
| `docs/decisions` | Architecture decision records. |
| `docs/modules` | Per-sprint implementation notes and acceptance results. |
| `docker-compose.yml` | Local Postgres only. |

## Prerequisites

- Python 3.13+
- Node.js (current LTS or newer; developed on 26) and pnpm 12
- Docker with Compose

## Local setup

```bash
cp .env.example .env
docker compose up -d --wait

# API (terminal 1)
cd services/api
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000

# Web (terminal 2)
cd apps/web
pnpm install
pnpm dev
```

- Web app: http://localhost:5173
- Health check: http://localhost:8000/api/v1/health
- API docs (disabled when `ENVIRONMENT=production`): http://localhost:8000/api/v1/docs

The web dev server proxies `/api` to the API on port 8000.

## Environment variables

Set in `.env` at the repository root (never committed). The API refuses to start if a value is missing or malformed.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | none | Postgres URL, `postgresql+psycopg://user:pass@host:port/db` |
| `ENVIRONMENT` | no | `development` | `development`, `test` or `production` |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | no | `mls`, `mls`, `mls`, `5432` | Used only by `docker-compose.yml` |

## Checks

CI (`.github/workflows/ci.yml`) runs the same commands on every pull request and on pushes to `main`.

```bash
# API (needs Postgres running), from services/api
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest

# Web, from apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## API conventions

- Base path `/api/v1`; JSON; UTC ISO 8601 timestamps.
- Every response carries `X-Request-ID`. Send your own (8–64 characters of `A-Z a-z 0-9 . _ -`) to correlate logs.
- Errors use one envelope:

  ```json
  {
    "error": {
      "code": "validation_error",
      "message": "Request validation failed.",
      "request_id": "…",
      "details": [{ "field": "query.limit", "message": "…" }]
    }
  }
  ```

- Collections use cursor pagination: `limit` (1–100, default 20) and `cursor`; responses are `{ "items": [...], "next_cursor": "…" | null }`.

## Database migrations

```bash
cd services/api
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```

## Known limitations

See [docs/modules/s0-foundation.md](docs/modules/s0-foundation.md).
