# ADR 0001: Initial stack (frontend, mobile, backend, database, tenancy, auth, storage, deployment)

- **Date:** 2026-11-16
- **Status:** Accepted for items marked *implemented*. Items marked *planned* are the intended direction and will be confirmed in the sprint that builds them.

This record covers INSTRUCTIONS.md §4.1 decisions 1–5 and 9 in one place because they were made together. Decisions 6–8 and 10 (AI provider, agent orchestration, vector search, Neo4j/Temporal/Kafka/Kong) get their own records when the relevant sprint introduces them.

## Context

The project is built by one developer with limited time, in sprints sized to a single working session. The blueprint names a large enterprise stack; INSTRUCTIONS.md §2.4 says to introduce it in stages and prefer a working vertical slice. The company has not yet stated mandatory technologies or hosting (§14 question 8), so every choice below is kept replaceable behind a boundary.

## 1. Frontend framework and mobile approach — *implemented (shell)*

- **Options:** React + Vite SPA; Next.js; native mobile app.
- **Decision:** React + Vite single-page app, responsive, to become an installable PWA. No native app.
- **Trade-offs:** No server-side rendering (not needed for an authenticated workspace). A PWA cannot use every native device feature. If the company requires a native app (§14 question 7), it will reuse the same versioned API.

## 2. Backend framework — *implemented*

- **Options:** FastAPI (Python); Next.js route handlers; NestJS.
- **Decision:** FastAPI modular monolith. One directory per feature under `services/api/app/modules`, shared code under `app/core`. A module uses another module only through its service functions.
- **Why:** OpenAPI is generated from the code, Pydantic validates both requests and AI output, and LangGraph, image processing and simulation are Python-native.
- **Trade-offs:** Two languages in the repo. The web client's types will be generated from the OpenAPI schema to keep them in step. Database access is synchronous (SQLAlchemy 2 + psycopg 3), which is simpler and adequate at demo scale.

## 3. Primary database and tenancy model — *database implemented, tenancy planned (Sprint 1)*

- **Decision:** PostgreSQL is the single source of truth, with Alembic migrations. Tenancy is a shared schema with an `organisation_id` column on every tenant-owned table, enforced by one server-side scoping dependency and proven by cross-tenant tests.
- **Options rejected:** Schema-per-tenant or database-per-tenant (heavy to migrate and operate at this stage).
- **Trade-offs:** Isolation depends on every query going through the scoping layer. Postgres row-level security can be added later as a second line of defence.

## 4. Authentication — *planned (Sprint 1)*

- **Decision:** Local authentication: Argon2 password hashes and server-side sessions in an httpOnly, SameSite cookie. API keys with scopes for third-party clients come later (Module 11).
- **Options rejected for now:** A hosted identity provider (adds an external dependency and account the company has not chosen).
- **Trade-offs:** The project owns password reset and session handling. The auth module boundary allows a provider to replace it.

## 5. Object storage — *planned (Sprint 6)*

- **Decision:** A storage interface with a local-filesystem adapter for development and an S3-compatible adapter for deployment. Originals are private; display uses separate derivatives.
- **Trade-offs:** The specific hosted bucket provider is not chosen yet; any S3-compatible service fits the adapter.

## 9. Deployment platform — *planned (Sprint 5)*

- **Decision:** Render for web, API, worker and managed Postgres, as suggested in INSTRUCTIONS.md Module 15.
- **Trade-offs:** Free-tier services sleep when idle and free databases expire; acceptable for a demo, not for production. Nothing is deployed yet.
- **Update 2026-11-17:** the demo runs as one container, not separate services. See ADR 0002.

## Consequences

- Local development needs Python, Node and Docker (for Postgres).
- Python dependencies are declared with version ranges in `pyproject.toml` and are not yet locked to exact versions.
- TypeScript is pinned to 6.x because `typescript-eslint` does not yet support TypeScript 7.
