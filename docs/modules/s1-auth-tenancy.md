# Sprint 1: Authentication and tenancy core (Module 1, part a)

Completed 2026-11-16. Part b (invitations, role assignment, password reset, profile, organisation switcher, seed data, admin screens) is Sprint 2.

## Scope delivered

- Tables: `users`, `auth_sessions`, `organisations`, `organisation_memberships`, `audit_events` (one Alembic migration).
- Sign-in with email and password. Passwords are hashed with Argon2id. The session token is random, sent only as an httpOnly `SameSite=Lax` cookie (`Secure` in production), and stored only as a SHA-256 hash.
- Sign-out revokes the session on the server. Sessions expire after `SESSION_TTL_HOURS`. Deactivating a user ends their sessions.
- Sign-in rate limit: 10 failures per email or 30 per IP address in 15 minutes, counted from the audit log so it holds across processes.
- Tenant scoping (`TenantScope`) and central permission checks (`require`). See `docs/security/rbac-matrix.md`.
- Audit log with a tenant-scoped, admin-only read endpoint.
- Command to create the first platform administrator.
- Web: sign-in form, signed-in view with the user's organisations and roles, sign-out.
- Keyset pagination helper `paginate` in `app/core/pagination.py`, used by every list endpoint.

## Endpoints

| Method and path | Access |
|---|---|
| `POST /api/v1/auth/login` | public, rate limited |
| `POST /api/v1/auth/logout` | signed in |
| `GET /api/v1/auth/me` | signed in |
| `GET /api/v1/organisations` | signed in; own organisations (platform admin: all) |
| `POST /api/v1/organisations` | platform admin |
| `GET /api/v1/organisations/current` | `organisation:read` |
| `GET /api/v1/organisations/current/members` | `member:read` |
| `GET /api/v1/audit-events` | `audit:read` |

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Signed-in user | `CurrentUser` from `app/modules/auth/deps.py` |
| Tenant-scoped route with a permission | `ctx: Annotated[TenantContext, Depends(require("x:y"))]` from `app/modules/organisations/deps.py`, then filter by `ctx.organisation_id` |
| New permission | Add to `Permission` and `ROLE_PERMISSIONS` in `app/modules/organisations/permissions.py` and to `docs/security/rbac-matrix.md` |
| Audit a sensitive action | `audit.record(session, "noun.verb", ...)` from `app/modules/audit/service.py` |
| Keep an audit event when the request then fails | `session.commit()` after `audit.record`, before raising |
| List endpoint | `paginate(session, stmt, page, sort=..., id_column=...)` |
| Script or worker outside the web app | `import app.main` first so every model is registered |
| Test data | `make_user`, `make_org`, `login_as` fixtures in `tests/conftest.py` |

## Acceptance criteria (INSTRUCTIONS.md Module 1)

| Criterion | Result |
|---|---|
| Users can authenticate | Met. Tested, and checked live through the web dev server. |
| An administrator can create/invite users and assign roles | **Not met yet.** Only the platform-admin bootstrap command exists. Sprint 2. |
| Users can only access authorised organisations and resources | Met for everything that exists so far. |
| Automated tests prove cross-tenant access is blocked | Met: `tests/test_tenancy.py`. |
| API errors do not leak secrets or internal stack traces | Met: Sprint 0 tests, plus sign-in gives the same answer for a wrong password and an unknown email. |

Checks run locally: API `ruff format --check`, `ruff check`, `mypy` (strict), `alembic upgrade head`, `alembic check`, `pytest` (30 passed); web `eslint`, `prettier --check`, `tsc --noEmit`, `vitest` (5 passed), `vite build`. Live: bootstrap command, sign-in, create organisation, audit list, sign-out through `http://localhost:5173`.

A bug found by the live check and fixed with a regression test: the bootstrap command failed because models from other modules were not loaded outside the web app.

## Known limitations

- No way to add a user to an organisation except directly in the database (added in Sprint 2).
- No password reset or change yet (added in Sprint 2).
- One role per user per organisation.
- The rate limit can be used to lock a known email out of sign-in for up to 15 minutes. It has no `Retry-After` header.
- The client IP address is taken from the connection. Behind a reverse proxy this is the proxy's address unless `FORWARDED_ALLOW_IPS` names the proxy (added in Sprint 5).
- CSRF protection relies on the `SameSite=Lax` cookie and on there being no cross-origin (CORS) access. Revisit if the web app and API are deployed on different sites (Sprint 5).
- Expired and revoked session rows are not purged.
- Sessions have a fixed lifetime; activity does not extend them.
- Not run on GitHub CI yet; nothing has been pushed.

## Next

Sprint 2: invitations and admin UI (Module 1, part b).
