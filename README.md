# AI-Native MLS

An API-first, AI-assisted Multiple Listing Service for real-estate professionals. The full product definition and module roadmap are in [INSTRUCTIONS.md](INSTRUCTIONS.md).

**Status:** Sprints 0–2 are complete: foundation; sign-in, organisations (tenants), role-based permissions and an audit log; invitations, member and role management, profile, password change and reset, organisation switcher. Module 1 is complete. Listings, media and AI features are not built yet. There is no live demo URL yet.

No email is sent by the system. Invitation and password-reset links are shown once to the administrator, who passes them on.

## Layout

| Path | Contents |
|---|---|
| `services/api` | FastAPI modular monolith. Shared code in `app/core`, one directory per feature in `app/modules`. |
| `apps/web` | React + Vite web app (responsive; PWA planned). |
| `docs/decisions` | Architecture decision records. |
| `docs/security` | Role and permission matrix. |
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

Load local demo data (three organisations and six users; refuses to run when `ENVIRONMENT=production`):

```bash
cd services/api
.venv/bin/python -m app.seed
```

Every seeded user signs in with the password `local-dev-password`. These accounts exist only in your local database.

| Email | Role |
|---|---|
| `platform.admin@demo.example.com` | Platform administrator |
| `mls.admin@demo.example.com` | MLS administrator, Demo MLS |
| `sunrise.admin@demo.example.com` | Brokerage administrator, Sunrise Realty |
| `sunrise.agent@demo.example.com` | Agent, Sunrise Realty |
| `harbour.admin@demo.example.com` | Brokerage administrator, Harbour Homes |
| `two.orgs@demo.example.com` | Broker at Sunrise Realty, agent at Harbour Homes |

Or create only a platform administrator of your own (the password is prompted for, minimum 12 characters):

```bash
cd services/api
.venv/bin/python -m app.modules.auth.cli create-platform-admin --email you@example.com --name "Your Name"
```

- Web app (sign in here): http://localhost:5173
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
| `SESSION_TTL_HOURS` | no | `12` | How long a sign-in lasts (1–720) |
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

- Browser sign-in uses an httpOnly session cookie set by `POST /api/v1/auth/login`. API keys for third-party clients come in a later sprint.
- Tenant-scoped endpoints act in one organisation. Send `X-Organisation-ID`; it may be omitted when you belong to exactly one organisation. Asking for an organisation you cannot access returns 403 whether or not it exists.
- Collections use cursor pagination: `limit` (1–100, default 20) and `cursor`; responses are `{ "items": [...], "next_cursor": "…" | null }`.

## Database migrations

```bash
cd services/api
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```

## Known limitations

See the notes per sprint: [Sprint 0](docs/modules/s0-foundation.md), [Sprint 1](docs/modules/s1-auth-tenancy.md), [Sprint 2](docs/modules/s2-invitations-admin.md).
