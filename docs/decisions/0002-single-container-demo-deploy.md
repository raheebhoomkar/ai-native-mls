# ADR 0002: Demo deployment as a single container

- **Date:** 2026-11-17
- **Status:** Accepted for the demo deployment. Revisit before any production deployment.

## Context

ADR 0001 planned Render with separate web, API and worker services. The web app authenticates with a `SameSite=Lax` session cookie and calls `/api/...` on its own origin. Two Render services would have two origins, which needs either cross-site cookies and CORS, or a rewrite rule whose target hostname is only known after the first deploy.

## Options considered

1. Static site plus API service, with a rewrite from the static site to the API.
2. Static site plus API service on different origins, with CORS and `SameSite=None` cookies.
3. One container: the API also serves the built web app.

## Decision

Option 3. A multi-stage `Dockerfile` builds the web app and copies it into the API image. When `WEB_DIST_DIR` is set, the API mounts that directory at `/`, after the `/api/v1` routes.

## Why

- Same origin, so the cookie, CSRF posture and API paths are identical in development, CI and the demo. No CORS.
- One free service instead of two.
- The exact image that is deployed can be built and tested locally and in CI, including the browser end-to-end test. Nothing depends on a hostname that is unknown in advance.
- It is not tied to Render: any host that runs a container and provides Postgres works.

## Trade-offs

- Static files are served by the Python process, without a CDN. Fine for a demo; slower than a static host under load.
- Web and API deploy together and cannot scale separately.
- The background worker (Sprint 6) will be a second process. It can start from the same image with a different command.

## Consequences

- Splitting later is cheap: unset `WEB_DIST_DIR`, host `apps/web/dist` anywhere, and solve the cross-origin question then.
- Migrations and optional demo seeding run at container start (`services/api/start.sh`), because free Render services have no separate release step or shell.
