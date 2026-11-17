# AI-Native MLS

An API-first, AI-assisted Multiple Listing Service for real-estate professionals. The full product definition and module roadmap are in [INSTRUCTIONS.md](INSTRUCTIONS.md).

**Status:** all 23 sprints (S0 to S22) are built and pass their checks locally. Not deployed yet.

**Live demo:** not deployed yet. Deploy to Vercel with [docs/deployment/vercel.md](docs/deployment/vercel.md), then put the URL here. Demo accounts are listed below; on a deployed demo their password is the `SEED_PASSWORD` set in the host, never in this repository.

| Read | For |
|---|---|
| [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) | Setup, demo accounts, automated checks, and a feature-by-feature test walkthrough |
| [docs/DEMO.md](docs/DEMO.md) | A 30-minute guided demo of every required feature, from draft listing to sold |
| [docs/architecture.md](docs/architecture.md) | System diagram, modules, agent workflow diagram, ERD, API docs |
| [docs/known-limitations.md](docs/known-limitations.md) | What is not verified or not built, and the roadmap |
| [docs/deployment/vercel.md](docs/deployment/vercel.md) | Deploying (Vercel; Render in `render.md`) |
| [docs/operations/runbooks.md](docs/operations/runbooks.md) | Monitoring, incidents, backup and restore, retention |
| [docs/api/developer-guide.md](docs/api/developer-guide.md) | API keys, webhooks, sample client |
| [docs/handover-checklist.md](docs/handover-checklist.md) | Release tag and transfer steps |

## Features

- **Organisations and roles:** MLS, brokerages and agents as tenants; role-based permissions; invitations by one-time link; platform administration; audit log with filters.
- **Listings:** properties and listings with a draft, review, active, sold and archived lifecycle; search, filters, sharing between organisations; CSV import with Indian formats and provenance; edit conflicts shown side by side.
- **Photos and AI:** uploads with thumbnails; AI suggestions of features seen in the photos, each accepted, edited or rejected by a person; privacy redaction (faces, plates, phone numbers, watermarks, signs) into an approved copy. AI never changes what the agent entered.
- **Policy checks:** listing text checked against an illustrative India policy (word rules plus an AI check), with a review queue, decisions and appeals. Decision support, never a legal opinion.
- **Location, search, valuation:** geocoding with source and precision, map and radius search; semantic search with the reason for each match; valuation from reported comparable sales with every assumption shown, or "insufficient data".
- **Agent workflow:** a LangGraph workflow (locate, read photos, policy check, human review, index, value) that pauses for people and blocks publication until they decide; cancel, retry, monitor.
- **Integration:** public API with scoped, rate-limited keys and idempotent retries; signed webhooks with retries and dead letters.
- **Team and app:** assignments, comments, private notes, notifications; role-aware dashboard; installable, responsive web app with offline notice.
- **Operations:** health checks, service health with alerts, daily cleanup, backup and restore scripts, load smoke test, dependency audit in CI.

Without any API key, every AI feature runs on a labelled demo adapter, so the whole app works offline. A `GEMINI_API_KEY` switches on Google Gemini.

No email is sent by the system. Invitation and password-reset links are shown once to the administrator, who passes them on.

## Layout

| Path | Contents |
|---|---|
| `services/api` | FastAPI modular monolith. Shared code in `app/core`, one directory per feature in `app/modules`. |
| `apps/web` | React + Vite web app (responsive, installable PWA). |
| `docs/decisions` | Architecture decision records. |
| `docs/security` | Role and permission matrix. |
| `docs/deployment` | How to deploy the demo. |
| `vercel.json`, `services/api/Dockerfile` | Vercel project: the web app on the CDN and the API as a container (ADR 0007). |
| `Dockerfile`, `render.yaml` | The single-container image (API plus web app) and the Render Blueprint. |
| `scripts` | Backup, restore, restore check, load smoke test, ERD generator. |
| `examples` | Sample API client and webhook receiver. |
| `docs/modules` | Per-sprint implementation notes and acceptance results. |
| `docker-compose.yml` | Local Postgres only. |

## Prerequisites

- Python 3.15+
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

# Background job worker (terminal 3): makes photo thumbnails, runs AI and redaction checks,
# deletes removed files
cd services/api
.venv/bin/python -m app.worker

# Web (terminal 2)
cd apps/web
pnpm install
pnpm dev
```

Load local demo data (three organisations, six users, five fictional listings marked `[Demo]` with two drawn demo photos each; refuses to run when `ENVIRONMENT=production`):

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
| `WEB_DIST_DIR` | no | unset | Directory of the built web app; when set, the API serves it (used in the container) |
| `SEED_DEMO_DATA`, `SEED_PASSWORD` | no | `false`, unset | Create demo data at container start. In production both are required for seeding, and the demo accounts get `SEED_PASSWORD` (12+ characters) |
| `MEDIA_STORAGE` | no | `local` | `local` (files under `MEDIA_ROOT`, one server only) or `s3` |
| `MEDIA_ROOT` | no | `<repo>/var/media` | Directory for uploaded files with local storage |
| `MEDIA_S3_BUCKET`, `MEDIA_S3_ENDPOINT_URL`, `MEDIA_S3_REGION` | with `s3` | unset | Private S3-compatible bucket; the endpoint is needed for services other than AWS. Credentials come from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` |
| `MEDIA_MAX_BYTES` | no | `10485760` | Largest upload (10 MB) |
| `MEDIA_RETENTION_DAYS` | no | `7` | Days before the files of removed media are deleted |
| `MEDIA_SIGNING_KEY` | in production | per process | Signs media download links (32+ characters). Unset outside production: links stop working when the API restarts |
| `GEMINI_API_KEY` | no | unset | Google Gemini key for photo extraction and for finding plates, phone numbers, watermarks and signs to redact. Unset: extraction answers with output labelled `[Demo]`, and redaction blurs faces only and marks the rest as not checked (ADR 0005). The free tier may use what you send to improve Google's models, so send demo photos only (ADR 0004) |
| `GEMINI_MODEL` | no | `gemini-3.5-flash` | Gemini model name |
| `AI_TIMEOUT_SECONDS` | no | `90` | Time limit for one provider call |
| `EMBEDDER`, `GEMINI_EMBEDDING_MODEL` | no | `demo`, `gemini-embedding-001` | Semantic search: `demo` (word matching, labelled) or `gemini` (needs the key; re-index after switching) |
| `VECTOR_STORE`, `QDRANT_URL`, `QDRANT_API_KEY` | no | `postgres` | Where listing vectors live: `postgres` or `qdrant` |
| `GEOCODER`, `NOMINATIM_URL`, `GEOCODER_USER_AGENT` | no | `demo` | `demo` (known city and locality centres, labelled) or `nominatim` (OpenStreetMap; set a user agent with a contact) |
| `CRON_SECRET` | on Vercel | unset | Turns on `GET /api/v1/ops/run-jobs` (runs due background jobs for up to 50 s) for callers sending `Authorization: Bearer <CRON_SECRET>` (16+ characters). Unset: that route answers 404 |
| `RUN_WORKER` | no | `true` | Container start script only: `false` keeps the in-container worker off (set in the Vercel image) |
| `FORWARDED_ALLOW_IPS` | no | `127.0.0.1` | Reverse proxies trusted for the client address (container start script) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | no | `mls`, `mls`, `mls`, `5432` | Used only by `docker-compose.yml` |

## Checks

CI (`.github/workflows/ci.yml`) runs the same commands on every pull request and on pushes to `main`.

```bash
# API (needs Postgres running; tests use their own database, <name>_test), from services/api
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest

# Web, from apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build

# Browser end-to-end test, from apps/web. Needs the app running with seed data and Chrome installed.
# Default target is the dev server; set E2E_BASE_URL and E2E_PASSWORD for another deployment.
pnpm e2e
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

- Browser sign-in uses an httpOnly session cookie set by `POST /api/v1/auth/login`. Other systems use API keys instead (`Authorization: Bearer <key>`, see `docs/api/developer-guide.md`).
- Tenant-scoped endpoints act in one organisation. Send `X-Organisation-ID`; it may be omitted when you belong to exactly one organisation. Asking for an organisation you cannot access returns 403 whether or not it exists.
- Money and areas are strings holding exact decimals, with a currency code or unit: `{ "amount": "25000000.00", "currency": "INR" }`.
- Editable records carry a `version`. Send the version you read with every change; `409 version_conflict` means someone else changed it first.
- Collections use cursor pagination: `limit` (1–100, default 20) and `cursor`; responses are `{ "items": [...], "next_cursor": "…" | null }`.

## API types in the web app

After changing the API, regenerate the web app's types:

```bash
cd apps/web && pnpm gen:api
```

## Database migrations

```bash
cd services/api
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```

## Known limitations

Summary and roadmap: [docs/known-limitations.md](docs/known-limitations.md). Each sprint note in [docs/modules](docs/modules) has the full list for its feature.
