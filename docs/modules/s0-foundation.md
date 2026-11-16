# Sprint 0: Repository foundation (Module 0)

Completed 2026-11-16.

## Scope delivered

- Monorepo layout: `services/api`, `apps/web`, `docs`.
- API: FastAPI app, `GET /api/v1/health` (checks the database), settings validated at startup, JSON logs with request IDs, one error envelope, cursor pagination helper, SQLAlchemy session with one transaction per request, Alembic wired to the same settings.
- Web: React + Vite shell that calls the health endpoint and shows operational, error (with request ID) or unreachable. The "Check again" button works.
- Local Postgres via Docker Compose.
- Formatting, linting, type checking and tests for both sides; GitHub Actions workflow running them.
- `.gitignore`, `.env.example`, README, ADR 0001.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Expected client-visible failure | `raise AppError(status, code, message, details)` from `app/core/errors.py` |
| Database session | `SessionDep` from `app/core/db.py` |
| New table | Subclass `Base` from `app/core/db.py`, then `alembic revision --autogenerate` |
| Collection endpoint | `PageParamsDep`, `Page[T]`, `encode_cursor` from `app/core/pagination.py` |
| Logging | `logging.getLogger(__name__)`; pass fields with `extra={...}` |
| New feature | New directory `app/modules/<name>/`, router registered in `app/main.py` |

## Acceptance criteria (INSTRUCTIONS.md Module 0)

| Criterion | Result |
|---|---|
| A new developer can follow README and run the project locally | Commands in README were the ones run during this sprint. Not yet verified on a second machine. |
| Web app and API start | Verified: web 200 on :5173, API 200 on :8000. |
| Health endpoint responds | Verified: 200 with database up, 503 error envelope with database stopped, 200 again after restart. |
| CI passes | Workflow written; every command in it passes locally. **Not yet run on GitHub** because nothing has been pushed. |
| No secrets are committed | Only local-development Postgres credentials (`mls`/`mls`) appear, in `.env.example`, `docker-compose.yml` and the CI service definition. `.env` is ignored. |
| Stack decisions and trade-offs documented | `docs/decisions/0001-initial-stack.md`. |

Checks run locally: API `ruff format --check`, `ruff check`, `mypy` (strict), `alembic upgrade head`, `pytest` (10 passed); web `eslint`, `prettier --check`, `tsc --noEmit`, `vitest` (3 passed), `vite build`.

## Known limitations

- Python dependencies use version ranges; there is no lock file.
- No rate limiting, authentication or CORS configuration yet (the dev server proxies `/api`, so the browser calls are same-origin). These arrive with Sprint 1 and Sprint 5.
- The API tests need a running Postgres.
- No migrations exist yet because there are no tables.
- The web shell is not yet a PWA.

## Outstanding inputs

- `AI_Native_MLS_Architecture_Blueprint.pdf` is not in the repository.
- The separate company email specification is not in the repository.
- INSTRUCTIONS.md §14 questions still unanswered by the company: 2 (product type), 3 (RESO version), 5 (roles and visibility rules), 6 (datasets and sandbox credentials), 8 (mandated technologies), 9 (deadline and rubric), 10 (repository transfer).

## Assumptions made by the developer (reversible, not confirmed by the company)

- Target market India: INR, explicit area units, no US Fair Housing or Clear Cooperation rules.
- Responsive web/PWA instead of a native mobile app.
- Gemini free tier as the first real AI provider, behind an interface.

## Next

Sprint 1: authentication and tenancy core (Module 1, part a).
