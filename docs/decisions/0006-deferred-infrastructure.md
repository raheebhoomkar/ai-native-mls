# ADR 0006: Infrastructure from the blueprint that is deferred, and when to add it

- **Date:** 2026-11-17
- **Status:** Accepted.

## Context

The product blueprint (INSTRUCTIONS.md, Module 14) names Kong, Temporal, Neo4j, Kafka, Debezium, Flink and TimescaleDB as target infrastructure, to be added only when a real use case justifies it. Each one is another service to deploy, secure, back up, upgrade and watch. The demo runs on one container and one Postgres (ADR 0002) and is operated by a student team. Nothing here is deployed, and no document should say it is.

## Decision

None of these is added now. Postgres and the modular monolith already do each job at the demo's scale. The table says what does the job today and what would make the component worth its cost.

| Component | Blueprint use | What does the job today | Add it when |
|---|---|---|---|
| **Kafka** | Event bus between services | Transactional outbox (`outbox_events`), written in the same transaction as the change; a job fans each event out to webhooks and the search index. Events are not lost between commit and publish. | More than one deployable service must consume the same events independently, or event volume outgrows a Postgres table (sustained thousands per second), or events must be replayed by consumers we do not run. |
| **Debezium (CDC)** | Stream database changes into Kafka | The outbox above. Changes are published by the code that makes them, with their meaning, not as raw row changes. | Kafka is in place, and a system needs changes from tables whose code we cannot change to write outbox events. |
| **Temporal** | Durable long-running workflows | LangGraph steps persisted as `workflow_runs` and steps, run by the Postgres job queue with bounded retries, leases and idempotent steps (ADR 0003, S15). Human review pauses a run as a stored state. | Workflows must wait for weeks, need timers or signals across many services, or the step count and history outgrow what the job table can show and retry. |
| **Flink** | Stream processing | Nothing needs continuous computation. Counts are queries; valuations and search updates run per change as jobs. | A real-time computation over an event stream is required (for example live market metrics over all listings) that a scheduled query cannot keep up with. |
| **TimescaleDB** | Time-series storage | Plain Postgres tables with indexes on time (`listing_status_history`, `api_key_usage`, `jobs`). Old usage rows are removed after 90 days. | A time-series workload with large volume and long retention appears, such as price indices per area kept for years, where queries over plain tables get slow. Being a Postgres extension, it is the cheapest to add of this list. |
| **Neo4j** | Graph queries over properties, participants and brokerages | Relational joins: memberships, listing sharing, import provenance (`listing_imports` and `listing_import_rows`, each row keeping its source record) and the audit log. Queries are one or two hops. | A product feature needs variable-depth relationship queries (for example ownership chains, referral networks, provenance across many imports) that are awkward or slow as recursive SQL. |
| **Kong (API gateway)** | Keys, rate limits, routing at the edge | The API itself: scoped API keys, per-key rate limits, usage log and idempotency keys (S17); Render's proxy terminates TLS. | Several backend services sit behind one public API, or limits must hold across many API instances at a request rate where the per-request database check is too costly, or partners need features such as OAuth client management. |

Two pieces of the blueprint were added because they had real use cases: Qdrant for semantic search (S13) and LangGraph for the workflow graph (S15).

## Operational plan if one is added

Each addition needs, before it ships: a new ADR with the measured need that triggered it; a container in `docker-compose.yml` for local work and a hosted plan in `render.yaml` (or a named provider); backups and a tested restore added to `docs/operations/runbooks.md`; its health added to `GET /api/v1/ops/status`; an adapter behind the existing interface (outbox consumer, job queue, storage) so the rest of the code does not change; and a fallback or failure mode the app shows instead of breaking.

## Consequences

- One database to back up, restore and watch; the runbooks stay short.
- The outbox and the job queue are the seams. Moving events to Kafka or workflows to Temporal replaces a consumer, not the code that writes events or queues work.
- Postgres takes all the load. The load smoke test and Service health show when it starts to struggle; that, not the blueprint, is the trigger for the next step.
