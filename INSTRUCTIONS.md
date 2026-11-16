# AI-Native Multiplayer Real Estate MLS

## Repository Instructions and Module-by-Module Build Plan

**Purpose:** This document is the primary build instruction for Claude
Code (or another AI coding assistant) working in this repository. It
defines the product, engineering principles, module sequence, acceptance
criteria, and rules for implementing the application incrementally.

**Project status:** Greenfield implementation. Treat the supplied
`AI_Native_MLS_Architecture_Blueprint.pdf` and any additional company
specifications as source requirements. Do not assume that this document
replaces missing company requirements or the separate specification
email.

------------------------------------------------------------------------

# 1. Mission

Build a real, usable, API-first, AI-native Multiple Listing Service
(MLS) enterprise application for real-estate professionals.

The application must support:

1.  A desktop/web experience.
2.  A mobile-friendly experience (initially responsive/PWA unless a
    native mobile app is explicitly required).
3.  Publicly documented, versioned APIs so approved third-party
    applications can integrate.
4.  Multi-user collaboration between agents, brokers, brokerages and
    administrators.
5.  AI-assisted property ingestion, media analysis, listing compliance,
    property matching and valuation.
6.  A modular multi-agent workflow, with traceable execution, clear
    state and safe human review.
7.  Automated testing, CI checks and a live demo deployment.
8.  A repository suitable for transfer to or hosting under WildCatter's
    GitHub organisation, subject to their permission.

The result must be a functioning application, not a static mock-up or a
collection of disconnected demos. Every visible control must work or be
clearly marked as not yet implemented.

## 1.1 Product definition

An MLS is a shared property-listing and collaboration platform for
real-estate professionals. Participating users can create, manage,
search, share and analyse property listings, subject to permissions and
brokerage rules.

This product should go beyond a conventional listing database by using
AI agents to reduce repetitive manual work and provide decision support.

**Core product principle:** AI should assist and automate appropriate
workflows, but must not silently invent property facts, make legally
consequential decisions without review, or publish unverified
information.

## 1.2 Important terminology

-   **Property:** The underlying real-world real-estate asset.
-   **Listing:** A time-bound marketing record for a property, with
    price, status, remarks, media and listing terms.
-   **Participant:** An agent, broker or other authorised real-estate
    professional.
-   **Brokerage:** An organisation to which participants may belong.
-   **MLS organisation:** The operator or administrator of the shared
    service.
-   **Comparable (comp):** Another property/listing/transaction used as
    evidence in market analysis.
-   **AI agent:** A bounded software component that receives a task,
    uses approved models/tools, returns structured results and records
    its reasoning summary/evidence.
-   **Human review:** An explicit approval or correction step for
    uncertain, sensitive or high-impact outcomes.

Do not treat a property and a listing as the same database entity. A
property can have multiple listings or historical listing records.

------------------------------------------------------------------------

# 2. Source requirements and implementation interpretation

The supplied architecture blueprint describes the following functional
capabilities:

## 2.1 Intelligent ingestion and media sanitisation

-   Accept property details and media such as image arrays, video and,
    where supported, 3D tours/drone files.
-   Use vision-language models (VLMs) to extract observable property
    characteristics.
-   Detect and redact specified sensitive or promotional visual
    elements, including faces, licence plates, phone numbers, agent
    promotional signage and watermarks, where legally and technically
    appropriate.
-   Resolve property coordinates and connect them to available municipal
    GIS layers, zoning, utilities, infrastructure, risk and
    school-boundary datasets.

**Implementation safeguards:** - AI-extracted attributes must include
confidence and evidence references. - Do not infer legally significant
measurements, ownership, room counts or amenities as confirmed facts
from a photograph alone. - Preserve original media in restricted storage
where required; create sanitised derivatives for display. - Redaction
must be reviewable. Never overwrite the only original file. - GIS
results must identify their data source, coverage and retrieval date. If
a data source is unavailable, show "not available"; do not fabricate
results.

## 2.2 RESO and listing compliance

-   Normalise incoming listing data to a consistent canonical model
    aligned with relevant RESO data definitions.
-   Analyse listing remarks for potentially discriminatory or otherwise
    prohibited language.
-   Support Clear Cooperation-related auditing if the product is
    operating in a jurisdiction and MLS context where those rules apply.
-   Flag issues, explain the flag and propose edits.

**Implementation safeguards:** - Treat RESO as a standards-alignment
target; do not claim certification or full RESO compliance without a
formal conformance review. - Fair Housing and Clear Cooperation are
US-specific concepts. Confirm the target market, applicable MLS rules,
policy version and legal interpretation with the company. Do not apply
US rules as if they were Indian law or universally applicable. -
Compliance AI must return evidence, rule/policy identifier, severity,
confidence and recommended action. - AI flags are decision support.
Provide a human review/appeal path and audit log. - Do not automatically
reject, suppress or rewrite a listing solely because of an unverified
model prediction.

## 2.3 Cognitive valuation, vector comps and trajectory prediction

-   Find comparable listings using structured filters and
    semantic/vector similarity.
-   Use property attributes, text and visual characteristics as matching
    signals.
-   Support price/market scenario analysis.
-   Provide Monte Carlo-style simulations for possible Days on Market
    (DOM) and multiple-offer outcomes when sufficient data exists.

**Implementation safeguards:** - Similarity is not the same as market
comparability. Use structured constraints such as geography, property
type, size, condition, transaction status and date alongside
embeddings. - Clearly distinguish asking prices from verified
closed-sale prices. - Show the source and date of every comp. - Do not
present a valuation as an appraisal or guaranteed sale price. - If there
is insufficient historical data, return "insufficient data" and show a
transparent illustrative scenario only when clearly labelled. - Do not
train or tune models from a single transaction. Use evaluated, versioned
datasets and models.

## 2.4 Infrastructure direction in the blueprint

The blueprint names:

-   Kong API Gateway
-   LangGraph agent orchestration
-   Temporal workflow durability
-   Qdrant vector database
-   Neo4j graph database
-   PostgreSQL and TimescaleDB
-   Apache Kafka and Apache Flink
-   Debezium change-data capture

These are target architecture components, not a requirement to run every
component in the first local prototype. Introduce infrastructure in
stages, with a documented reason, cost/operational impact and tested
integration. Prefer a reliable vertical slice over a large number of
empty services.

Suggested staged approach: - Start with PostgreSQL as the source of
truth, object storage abstraction, REST API and LangGraph-based AI
workflow. - Add Qdrant when semantic retrieval is implemented. - Add
Neo4j when relationship queries provide clear value. - Add Temporal when
workflows need durable long-running execution/retries beyond the initial
job system. - Add Kafka/Debezium/Flink when event volume, integration
needs or streaming analytics justify them. - Kong may be introduced for
gateway-level concerns; for an early demo, a well-secured API
service/reverse proxy may be sufficient. Keep the API design
gateway-ready.

Do not claim that a component is deployed if it is only represented by
an interface, stub or local mock.

------------------------------------------------------------------------

# 3. Working rules for Claude Code

Claude Code must follow these rules throughout the project.

## 3.1 Build one module at a time

-   Work only on the current module/phase requested by the developer.
-   Do not start the next module automatically.
-   Before coding, inspect the repository, read this file, inspect
    existing code and report the current state.
-   For the requested module, provide a short implementation plan and
    list files expected to change.
-   Implement the module end-to-end: data model, migrations,
    backend/API, frontend where relevant, validation, errors, tests and
    documentation.
-   Run relevant tests, formatting, linting and type checks.
-   Fix failures introduced by the change.
-   Summarise completed work, commands run, known limitations and exact
    next step.
-   Stop and wait for explicit approval before moving to the next
    module.

## 3.2 No fake completion

-   Never claim a feature works unless it has been implemented and
    tested.
-   Do not leave buttons that do nothing.
-   Do not return hardcoded success responses for core workflows.
-   Mocks are permitted only behind explicit development/demo adapters
    and must be labelled in the UI and documentation.
-   Do not substitute mock AI output for a real model call without
    clearly identifying it.
-   Never invent API keys, secrets, property records, market data or
    legal rules.
-   Do not silently swallow errors.

## 3.3 Engineering quality

-   Use clear module boundaries and small, maintainable files.
-   Prefer typed request/response schemas and explicit validation.
-   Use database migrations; do not rely on manually created production
    tables.
-   Use environment variables for configuration and secrets.
-   Add structured logs and correlation/request IDs.
-   Use UTC for stored timestamps; render local time in the UI.
-   Use decimal/numeric types for currency, never binary floating point
    for persisted money.
-   Add pagination, filtering and sorting to collection APIs.
-   Add indexes for common queries.
-   Use transactions for related writes.
-   Design for tenant isolation from the beginning.
-   Keep AI providers, storage providers, geospatial providers and
    external data sources behind interfaces/adapters.
-   Avoid unnecessary microservices at the start. A modular monolith is
    acceptable for the first deployable version, with clear boundaries
    that allow extraction later.
-   Do not commit generated files, build outputs, virtual environments,
    secrets or local databases.

## 3.4 Security and privacy

-   Implement authentication and role-based access control (RBAC).
-   Enforce authorisation on the server for every protected resource;
    frontend hiding is not security.
-   Prevent cross-tenant data access.
-   Validate file type, size and content; use safe filenames and private
    object storage.
-   Do not expose original media or private contact details to
    unauthorised users.
-   Protect against injection, broken access control, insecure direct
    object references, SSRF and unsafe file uploads.
-   Apply rate limits to authentication, uploads and expensive AI
    endpoints.
-   Store secrets only in environment variables or a secrets manager.
-   Maintain audit events for sensitive actions.
-   Use least-privilege service credentials.
-   Add data retention/deletion procedures appropriate to the final
    market and company policy.

## 3.5 AI safety and observability

Every AI task should record: - Task/run ID and listing ID. - Agent name
and version. - Model/provider and model version, when available. - Input
references (not unnecessary copies of sensitive data). - Structured
output. - Confidence/uncertainty where supported. - Evidence
references. - Start/end time, status and retry information. - Human
decision and reviewer, if applicable.

AI outputs must be schema-validated. If output parsing fails, retry
safely or mark the task as failed for review. Do not allow untrusted
listing text or uploaded content to override system instructions or
invoke arbitrary tools.

------------------------------------------------------------------------

# 4. Proposed repository structure

Use a monorepo unless the company directs otherwise.

``` text
ai-native-mls/
├── INSTRUCTIONS.md
├── README.md
├── CONTRIBUTING.md
├── LICENSE
├── .gitignore
├── .env.example
├── docker-compose.yml
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── decisions/
│   ├── modules/
│   ├── security/
│   └── deployment/
├── apps/
│   ├── web/                 # Desktop/web application
│   └── mobile/              # Responsive/PWA or native app, based on decision
├── services/
│   ├── api/                 # Main API and business logic
│   ├── ai-orchestrator/     # LangGraph workflows and agent definitions
│   └── worker/              # Async/background jobs
├── packages/
│   ├── shared-types/
│   ├── api-client/
│   ├── ui/
│   └── config/
├── infrastructure/
│   ├── docker/
│   ├── migrations/
│   └── deployment/
├── scripts/
└── tests/
    ├── integration/
    ├── e2e/
    └── fixtures/
```

Adapt this structure to the selected stack after documenting the
decision. Do not create empty folders purely to match this tree.

## 4.1 Architecture decision records

For major decisions, create a short ADR in `docs/decisions/`,
including: - Context/problem. - Options considered. - Decision. -
Trade-offs. - Consequences. - Date and status.

At minimum, document decisions for: 1. Frontend framework and mobile
approach. 2. Backend framework. 3. Primary database and tenancy model.
4. Authentication provider/approach. 5. Object storage. 6. AI model
provider and fallback strategy. 7. Agent orchestration. 8. Vector
search. 9. Deployment platform. 10. Whether/when to add Neo4j, Temporal,
Kafka and Kong.

Do not assume the blueprint's suggested enterprise products are all
available, free or compatible with the chosen hosting platform.

------------------------------------------------------------------------

# 5. Product roles and permissions

Implement permissions centrally and test them.

Initial roles:

  -----------------------------------------------------------------------
  Role                                Main capabilities
  ----------------------------------- -----------------------------------
  Platform administrator              Manage platform settings,
                                      organisations, users, policies and
                                      audit records

  MLS administrator                   Manage MLS membership, listing
                                      rules, data quality and review
                                      queues

  Brokerage administrator             Manage brokerage profile, offices,
                                      team members and brokerage listings

  Broker                              Manage assigned agents and
                                      brokerage listings according to
                                      permissions

  Agent                               Create and manage permitted
                                      listings, upload media, search and
                                      collaborate

  Read-only/API consumer              Access only the resources granted
                                      to its account/API scopes
  -----------------------------------------------------------------------

A user may have more than one role or belong to more than one
organisation if the company requirements permit it.

Define tenant boundaries explicitly. A user from Brokerage A must not be
able to access private records belonging to Brokerage B unless a sharing
rule grants access.

Do not assume all listings are visible to every user. Implement listing
visibility and sharing rules as explicit policy decisions.

------------------------------------------------------------------------

# 6. Module-by-module implementation roadmap

Implement in this order. A module is complete only when its acceptance
criteria pass.

## Module 0 --- Repository foundation and engineering setup

**Goal:** Create a reproducible development environment.

Tasks: - Initialise the monorepo and Git. - Add `INSTRUCTIONS.md`,
README, `.gitignore` and `.env.example`. - Select the initial stack and
document ADRs. - Configure formatting, linting, type checking and test
runner. - Add local development services with Docker Compose where
appropriate. - Add health-check endpoint. - Add CI workflow to install
dependencies, lint, type-check and test. - Add a minimal web shell and
API service that start successfully. - Add structured logging and
configuration validation.

Acceptance criteria: - A new developer can follow README and run the
project locally. - Web app and API start. - Health endpoint responds. -
CI passes. - No secrets are committed. - Stack decisions and known
trade-offs are documented.

**Stop after this module and request approval.**

## Module 1 --- Authentication, organisations, tenancy and RBAC

**Goal:** Establish secure multi-user foundations.

Tasks: - Implement sign-up/invitation and login/logout flows appropriate
to the selected auth approach. - Implement user profile. - Implement
organisation/brokerage entities. - Implement organisation membership and
roles. - Implement server-side RBAC and tenant scoping. - Add password
reset/session handling if using local authentication. - Add audit events
for login, role changes, invitations and sensitive access. - Create seed
data for local development only.

Acceptance criteria: - Users can authenticate. - An administrator can
create/invite users and assign roles. - Users can only access authorised
organisations and resources. - Automated tests prove cross-tenant access
is blocked. - API errors do not leak secrets or internal stack traces.

## Module 2 --- Core property and listing management

**Goal:** Build the foundational MLS data model and workflows.

Create separate entities for: - Property. - Listing. -
Participant/agent. - Brokerage/organisation. - Office/team, if
required. - Listing media. - Listing status/history. - Listing
collaboration/sharing. - Audit event.

A property should contain stable physical/location identity fields. A
listing should contain marketing and transaction lifecycle fields. Avoid
duplicating the same source-of-truth fields unnecessarily.

Tasks: - Design migrations and indexes. - Implement
create/read/update/archive workflows. - Implement listing status
transitions with validation. - Implement property-to-listing and
listing-to-agent/brokerage relationships. - Implement draft, pending
review, active, temporarily off-market, sold/closed, withdrawn and
expired states as appropriate to company rules. - Add listing history
and audit trail. - Add search filters, pagination and sorting. - Build
desktop listing table, listing detail and create/edit forms. - Make
screens responsive.

Acceptance criteria: - An authorised agent can create and edit a
listing. - A listing is linked to the correct property, agent and
brokerage. - Invalid status transitions are rejected. - Listing history
is visible to authorised users. - Search and filters work against
persisted data. - Role and tenant permissions are tested.

## Module 3 --- Media upload and secure asset management

**Goal:** Support real property photos and other media.

Tasks: - Create a storage abstraction (local development storage plus
chosen production object storage). - Implement secure, signed
upload/download flows where supported. - Validate file size, MIME type
and file signatures. - Store metadata, ownership, upload status and
checksum. - Support image galleries and thumbnails. - Add asynchronous
processing job records. - Preserve originals and create derivative
assets separately. - Add deletion/retention handling. - Show upload
progress, failures and retry controls.

Acceptance criteria: - Users can upload, view and remove authorised
media. - Unauthorised users cannot access private assets. - Invalid
files are rejected. - Upload state and errors are visible. - Local and
production storage use the same abstraction.

## Module 4 --- AI ingestion and visual feature extraction

**Goal:** Analyse uploaded media and turn observable information into
structured suggestions.

Agents/services: 1. Media preprocessing agent. 2. Vision/feature
extraction agent. 3. Attribute normalisation agent. 4.
Confidence/evidence validation step.

Tasks: - Define a provider-independent VLM interface. - Build an initial
provider adapter using the chosen available model. - Send authorised
images for analysis. - Request structured JSON for observable features
such as room type, visible flooring, visible appliances, windows,
balcony evidence and condition cues. - Validate output against a typed
schema. - Store model, version, confidence and evidence references. -
Present extracted suggestions beside the listing form. - Allow an
authorised user to accept, edit or reject each suggestion. - Record the
human decision. - Handle unavailable provider, timeout, rate limit and
malformed output. - Add explicit demo mode only if no real model
credentials are available.

Acceptance criteria: - An uploaded image can trigger a real model
analysis when configured. - Results are structured and linked to source
media. - Uncertain attributes are labelled uncertain. - No AI result
silently overwrites agent-entered verified data. - Human corrections are
stored. - Tests cover valid, invalid and failed model responses.

## Module 5 --- Image sanitisation and redaction

**Goal:** Detect and redact selected sensitive/promotional visual
content.

Tasks: - Define the supported detection categories and policy. - Build
detector interface and provider/algorithm adapters. - Detect faces,
licence plates, phone numbers, watermarks and promotional signage where
feasible. - Generate a redaction preview. - Store sanitised derivative
separately from original. - Let authorised reviewers approve or reject
the derivative. - Record what was detected, what was redacted and the
method/version. - Avoid claiming perfect detection; show limitations and
review status.

Acceptance criteria: - The system can process a test image and produce a
reviewable derivative. - Original media remains protected. - Redaction
is not applied destructively. - A reviewer can approve/reject the
result. - Failed or low-confidence detections are routed for review.

## Module 6 --- Listing standardisation and compliance workflow

**Goal:** Standardise listing data and flag potential policy issues.

Tasks: - Define canonical listing fields and a mapping layer for
external schemas. - Align field names/definitions with relevant RESO
concepts after confirming target MLS market and required RESO version. -
Build import validation and field normalisation. - Build a policy/rules
configuration model with policy version and jurisdiction. - Implement
language analysis for potentially discriminatory or prohibited
remarks. - Return structured flags with phrase/evidence, severity,
confidence, policy reference and suggested alternative. - Add reviewer
queue, decision, override and appeal/audit trail. - Add Clear
Cooperation monitoring only if the applicable company/MLS rules and
lawful data source are confirmed. - Do not scrape websites or social
platforms without authorisation and terms review.

Acceptance criteria: - Supported external field variants map to
canonical fields. - Invalid fields produce actionable validation
errors. - A test set of remarks produces explainable flags. - Reviewer
can accept, dismiss or request edits. - Policy version and reviewer
action are auditable. - The UI does not label the system "legally
compliant" merely because a scan passed.

## Module 7 --- Geospatial enrichment

**Goal:** Add useful location intelligence to listings.

Tasks: - Store validated coordinates and geocoding source. - Add map
view and location-based search. - Define adapters for geocoding and GIS
datasets. - Integrate only data sources for which access and licensing
are available. - Display nearby infrastructure/zoning/risk data with
source and update date. - Handle missing coverage and conflicting
results. - Avoid inferring legal zoning or risk status from an
unverified map layer.

Acceptance criteria: - Users can view authorised listings on a map. -
Location search works. - Enrichment data displays source and date. -
Missing data is represented honestly. - Coordinates and sensitive
location information follow access policy.

## Module 8 --- Semantic property search and vector comps

**Goal:** Find properties using both structured filters and semantic
similarity.

Tasks: - Define embedding model/provider interface and version. - Create
Qdrant collection with a dimension matching the selected embedding model
(do not hardcode 1024 unless the selected model outputs 1024). -
Generate embeddings for permitted listing text and/or media. - Store
listing ID, tenant/visibility metadata and embedding version in
payload. - Implement hybrid retrieval: structured filters
first/alongside vector similarity. - Add deduplication and
access-control filtering. - Show why a comp was matched and which
attributes contributed. - Re-index on relevant listing changes and
remove stale vectors. - Keep the relational database as source of truth.

Acceptance criteria: - A user can search using ordinary language and
structured filters. - Similar listings are returned with explainable
similarity signals. - Tenant/visibility constraints are enforced before
results are shown. - Embedding failures and re-indexing are
observable. - Results do not imply a valuation or legal comparability by
themselves.

## Module 9 --- Valuation and market trajectory simulation

**Goal:** Provide transparent, data-grounded decision support.

Tasks: - Define required training/reference data and data quality
rules. - Separate active asking prices from verified transaction
prices. - Build comp selection with geography, property type, area,
date, condition and other relevant fields. - Build a baseline valuation
method before adding complex models. - Implement Monte Carlo scenario
simulation for DOM and offer outcomes only when historical data supports
parameter estimates. - Make assumptions configurable and visible. -
Return a range, uncertainty, sample size and data freshness. - Track
prediction versus later outcome for evaluation. - Version models and
simulation parameters. - Add a clear "not an appraisal" disclaimer.

Acceptance criteria: - Valuation output shows its comps and
assumptions. - No unsupported numeric prediction is shown as fact. -
Insufficient data returns a clear unavailable state. - Simulation is
reproducible for a stored seed/configuration. - Evaluation metrics and
model version are recorded.

## Module 10 --- Multi-agent orchestration and durable workflows

**Goal:** Coordinate listing ingestion and review as an observable
workflow.

Use LangGraph for agent state and routing. Add Temporal only when
durable long-running execution/recovery is needed and can be deployed
reliably.

Initial workflow: 1. Listing submitted. 2. Media analysis. 3. Attribute
extraction/normalisation. 4. Media sanitisation. 5. Compliance analysis.
6. Geospatial enrichment. 7. Matching/comp retrieval. 8. Optional
valuation. 9. Validation and human-review gate. 10. Publication after
required approval.

Tasks: - Define a typed workflow state with IDs and status. - Define
agent input/output schemas and strict tool permissions. - Implement
idempotency and retry rules. - Implement conditional routing. - Add
timeouts and failure states. - Persist workflow runs, step status and
output references. - Add cancellation and retry controls. - Add
human-in-the-loop review nodes. - Add event notifications to the
frontend. - Prevent infinite agent loops and bound token/tool budgets. -
Add trace IDs linking API request, workflow and agent calls.

Acceptance criteria: - A listing can run through the workflow
end-to-end. - Each step's status and result are inspectable. - A failure
can be retried without duplicating records. - Human review pauses the
workflow and resumes after a decision. - Publication cannot bypass
required checks. - Tests cover success, failure, retry and review paths.

## Module 11 --- API platform and developer experience

**Goal:** Make the MLS extensible for external developers.

Tasks: - Publish versioned REST APIs under `/api/v1`. - Use consistent
schemas, pagination, filtering and error format. - Generate OpenAPI
documentation. - Implement API keys or OAuth2 client credentials as
appropriate. - Implement scopes and organisation-level permissions. -
Add rate limits, quotas, request IDs and usage logs. - Provide webhook
subscriptions for events such as listing created/updated/published. -
Sign webhook deliveries and support retries. - Add idempotency keys for
suitable write endpoints. - Provide a developer guide and example
integration. - Keep internal service endpoints separate from public
APIs.

Initial endpoint families: - `/api/v1/auth` - `/api/v1/users` -
`/api/v1/organisations` - `/api/v1/properties` - `/api/v1/listings` -
`/api/v1/media` - `/api/v1/agents` - `/api/v1/search` -
`/api/v1/comps` - `/api/v1/valuations` - `/api/v1/ai/jobs` -
`/api/v1/reviews` - `/api/v1/webhooks`

Acceptance criteria: - OpenAPI documentation is accessible in
non-production or authorised environments. - A sample third-party client
can authenticate and retrieve permitted listings. - Scopes and tenant
restrictions are tested. - Rate limits and errors are documented. -
Webhook signatures and retry behaviour are tested.

## Module 12 --- Multiplayer collaboration and notifications

**Goal:** Support real multi-user workflows.

Tasks: - Implement listing assignment and permitted collaboration. -
Implement comments/notes with visibility rules. - Implement review tasks
and notifications. - Add activity timeline. - Add real-time updates only
where they improve the workflow. - Record who changed what and when. -
Prevent conflicting edits using version checks or optimistic
concurrency. - Add notification preferences.

Acceptance criteria: - Multiple authorised users can collaborate on a
listing. - Private notes are not visible to unauthorised participants. -
Conflicting updates are detected and handled. - Activity history is
accurate. - Notifications link to the relevant authorised resource.

## Module 13 --- Desktop/mobile UX completion and admin console

**Goal:** Deliver a coherent product experience.

Required experiences: - Login and organisation selection. - Role-aware
dashboard. - Listing search and filters. - Listing detail with media
gallery and map. - Create/edit listing wizard. - AI analysis results and
correction UI. - Compliance review queue. - Comp and valuation view. -
Agent/brokerage management. - Workflow/job monitor. - API developer
area. - Platform/MLS administration. - Audit/activity view.

Requirements: - Responsive layouts for phone, tablet and desktop. -
Accessible labels, keyboard navigation and clear error states. -
Loading, empty, offline and failure states. - Consistent design
system. - Avoid decorative controls that do not work. - If a native app
is required, document the native approach and reuse shared API/types
where possible.

Acceptance criteria: - Primary workflows can be completed on desktop and
mobile-sized screens. - No critical screen overflows or hides essential
actions. - User permissions are reflected in navigation and enforced by
the API. - End-to-end tests cover the most important user journeys.

## Module 14 --- Event infrastructure, graph layer and production hardening

**Goal:** Introduce advanced infrastructure when justified and prepare a
robust demo/production deployment.

Tasks: - Add an outbox/event publication pattern to avoid losing events
between database commits and event publishing. - Add Debezium/Kafka CDC
only if the deployment environment supports it and the team can operate
it. - Add Neo4j for real graph use cases, such as
property/participant/brokerage relationships and provenance queries. -
Add TimescaleDB for meaningful time-series workloads. - Add Flink only
for real stream-processing needs. - Add Kong or another gateway where
required. - Add backups, restore testing, monitoring and alerting. - Add
load/security testing and dependency scanning. - Document data
retention, incident response and operational runbooks.

Acceptance criteria: - Each additional infrastructure component has a
documented use case and operational plan. - Events are not silently
lost; retries and dead-letter handling exist where applicable. - Backups
and restore procedure are tested. - Monitoring covers API health,
database health, background jobs and AI-provider failures. - Deployment
can be reproduced from documented configuration.

## Module 15 --- Demo readiness and handover

**Goal:** Prepare the project for company evaluation and GitHub
handover.

Tasks: - Deploy web, API, worker and required data services to Render or
another suitable platform. - Configure production secrets in the host's
secret manager. - Configure database migrations and seed only
non-sensitive demo data. - Add demo accounts with clearly documented
roles and safe sample data. - Create a demo script that covers the
complete listing lifecycle. - Add architecture diagram, ERD, agent
workflow diagram and API docs. - Add known limitations and roadmap. -
Verify mobile and desktop demo URLs. - Verify logs, health checks and
recovery from a failed background task. - Prepare repository transfer
steps; do not push to WildCatter's organisation until permission and
repository access are granted.

Acceptance criteria: - A reviewer can access the live demo. - Core
workflow works without developer intervention. - No real secrets or
private data appear in the repository or demo. - README explains setup,
architecture, features, limitations and demo credentials. - The project
is tagged with a release version. - Handover checklist is complete.

------------------------------------------------------------------------

# 7. Suggested core data model

This is a starting point. Refine it after receiving the company's
complete specification.

Core entities: - `User` - `Organisation` - `OrganisationMembership` -
`Role` / `Permission` - `Brokerage` - `Office` - `Participant`
(agent/broker profile) - `Property` - `Listing` -
`ListingStatusHistory` - `ListingMedia` - `MediaAnalysis` - `AIJob` -
`AgentRun` - `CompliancePolicy` - `ComplianceFinding` - `ReviewTask` -
`ReviewDecision` - `ComparableMatch` - `ValuationRun` -
`MarketObservation` - `Comment` - `Notification` -
`WebhookSubscription` - `WebhookDelivery` - `AuditEvent`

Important modelling rules: - `Property` is the durable asset record;
`Listing` is the marketing/transaction record. - Use immutable IDs
(UUID/ULID). - Include `organisation_id` or an equivalent tenant scope
on tenant-owned records. - Store currency code and amount separately. -
Use explicit units for area (for example square feet or square
metres). - Store source/provenance for imported or AI-derived fields. -
Use soft deletion only where it makes sense; define retention and
archival behaviour. - Keep status history rather than overwriting all
previous states. - Add optimistic concurrency/version fields for records
that can be edited by multiple users.

------------------------------------------------------------------------

# 8. API design conventions

Use consistent conventions:

-   Base path: `/api/v1`
-   JSON request/response bodies.
-   ISO 8601 timestamps in UTC.
-   UUID/ULID identifiers.
-   Pagination: `limit`, `cursor` (or documented `page`/`page_size`).
-   Consistent error envelope with machine-readable code, human-readable
    message and request ID.
-   Validation errors identify the invalid field.
-   Never expose database internals or stack traces.
-   Use appropriate HTTP methods and status codes.
-   Document authentication scopes and permissions per endpoint.
-   Use idempotency for retryable create/payment-like or external
    integration operations where appropriate.

Example listing response (illustrative only):

``` json
{
  "id": "lst_demo_001",
  "property_id": "prop_demo_001",
  "status": "DRAFT",
  "list_price": {
    "amount": "25000000.00",
    "currency": "INR"
  },
  "address": {
    "locality": "Powai",
    "city": "Mumbai",
    "country": "IN"
  },
  "bedrooms": 3,
  "bathrooms": 2,
  "ai_analysis_status": "PENDING_REVIEW"
}
```

Do not assume INR/Mumbai is the target market simply because it is the
developer's location. Confirm the product's intended country, currency,
MLS rules and data standards with the company. The sample above is only
illustrative.

------------------------------------------------------------------------

# 9. Frontend requirements

The interface should feel like a professional enterprise real-estate
workspace.

Design principles: - Clear navigation by role. - Information-dense but
readable tables. - Strong listing search and filters. - Property cards
with media, price, status and key facts. - Detailed listing page with
activity, media, AI findings and comps. - Visible workflow state (draft,
processing, review required, approved, active, rejected/needs
changes). - Explainable AI outputs with confidence and evidence. - Human
review controls for AI-generated suggestions. - Responsive design, not a
desktop-only layout squeezed onto mobile.

Do not spend time polishing animations before core workflows work.
Prioritise usability, reliability and clarity.

------------------------------------------------------------------------

# 10. Testing strategy

Every module must include appropriate tests.

Minimum test types: - Unit tests for business rules and utility
functions. - API tests for validation, permissions and error cases. -
Integration tests for database and storage interactions. - AI contract
tests using deterministic fixtures and mocked provider responses. -
End-to-end tests for key user journeys. - Security tests for tenant
isolation and access control. - Regression tests for bugs fixed.

Critical test scenarios: 1. User from one organisation cannot read
another organisation's private listing. 2. Agent cannot perform
administrator-only actions. 3. Invalid property/listing data is
rejected. 4. Uploaded unsupported file is rejected. 5. AI output that
fails schema validation is not saved as trusted data. 6. Low-confidence
compliance flag enters review. 7. Listing cannot publish while required
review is unresolved. 8. A failed AI job can be retried safely. 9.
Vector search respects listing visibility and tenant constraints. 10.
Public API credentials cannot access endpoints outside their scopes.

Do not use live external AI calls in the normal unit-test suite. Use
contract fixtures for deterministic tests, with a separate opt-in
integration test for real provider calls.

------------------------------------------------------------------------

# 11. CI/CD, Git and collaboration workflow

## 11.1 Branching

Suggested branches: - `main`: stable, deployable code. - `develop`:
integration branch if the team needs it. -
`feature/<module>-<short-description>`: feature work. -
`fix/<short-description>`: bug fixes.

Use pull requests for changes to `main`. Require CI checks before
merging.

## 11.2 Commit conventions

Use clear conventional-style messages, for example: -
`chore: initialise monorepo` -
`feat(auth): add organisation membership` -
`feat(listings): add listing lifecycle` -
`feat(ai): add visual feature extraction` -
`fix(search): enforce listing visibility` -
`test(compliance): add policy rule fixtures` -
`docs: add deployment guide`

## 11.3 Definition of done for every module

A module is done only when: - Requirements and scope are documented. -
Code is implemented and integrated. - Database migrations are included
where needed. - Validation and error handling exist. - Permissions and
security are checked. - Tests pass. - Lint/format/type checks pass. -
Documentation is updated. - No secrets or temporary debug code are
committed. - Known limitations are recorded. - A developer can run the
feature using documented steps.

## 11.4 GitHub setup commands

Run these locally from the project directory:

``` bash
mkdir ai-native-mls
cd ai-native-mls
git init
git branch -M main
```

After adding the initial files:

``` bash
git add .
git commit -m "chore: initialise AI-native MLS repository"
```

Create an empty repository on GitHub under the account/organisation
authorised by the company, then connect it:

``` bash
git remote add origin <YOUR_AUTHORISED_REPOSITORY_URL>
git push -u origin main
```

Do not guess the WildCatter repository URL or push to its organisation
before receiving permission. Keep your own private development
repository if appropriate, and transfer/mirror it only according to the
company's instructions.

------------------------------------------------------------------------

# 12. Claude Code operating prompt

Use this prompt at the beginning of a Claude Code session:

> You are the senior software architect and implementation engineer for
> this AI-Native MLS project. First read `INSTRUCTIONS.md`, `README.md`,
> all architecture decision records and the existing codebase. The goal
> is to build a real, secure, modular, API-first MLS product.
>
> Work strictly module by module. Do not implement future modules unless
> explicitly asked. Before coding, summarise the current repository
> state, identify the current module, list the requirements and
> acceptance criteria, propose a concise implementation plan and list
> expected files to change. Ask questions if a missing company
> requirement affects a major architecture or legal decision; otherwise
> document a reversible assumption.
>
> Implement the current module end-to-end, including migrations,
> backend, frontend, validation, authorisation, tests and documentation
> as relevant. Do not leave non-functional controls, fake success
> responses or unexplained mocks. Keep AI providers and external
> services behind interfaces. Treat AI output as untrusted, validate it,
> preserve provenance and use human review for high-impact decisions.
>
> Run all relevant tests, linting, formatting and type checks. Fix
> failures caused by your changes. At the end, report files changed,
> behaviour implemented, commands/tests run and their results, known
> limitations, manual setup still required, and the exact next module.
> Stop and wait for approval before continuing.
>
> Never expose secrets, invent external data or claim production
> readiness without evidence. Preserve existing working code and avoid
> unrelated refactoring.

## 12.1 Prompt to start a specific module

Use this template each time:

> Implement **Module \[NUMBER\] --- \[NAME\]** from `INSTRUCTIONS.md`.
>
> First inspect the repository and confirm which prerequisites are
> complete. Do not assume earlier modules are implemented unless the
> code proves it.
>
> Restate the module's scope and acceptance criteria. Identify any
> unresolved decision that blocks implementation. Then implement only
> this module end-to-end.
>
> Add or update tests and documentation. Run the required checks and fix
> failures. Do not start the next module. Finish with a concise
> completion report and wait for my approval.

## 12.2 Prompt for code review after a module

> Review the current module as a critical senior engineer. Do not add
> new features. Inspect for security issues, tenant isolation failures,
> broken permissions, data integrity problems, race conditions, poor
> error handling, unvalidated AI output, missing tests, inaccessible UI
> and dead controls. Run relevant tests and report findings by severity.
> Fix confirmed issues in scope, add regression tests and report
> anything that remains unresolved.

------------------------------------------------------------------------

# 13. Required documentation as the project grows

Keep these documents updated:

-   `README.md`: project overview, prerequisites, local setup, commands,
    environment variables, test instructions and demo URL.
-   `docs/architecture/system-overview.md`: architecture and service
    boundaries.
-   `docs/architecture/data-flow.md`: listing and AI data flows.
-   `docs/architecture/agent-workflows.md`: agent responsibilities,
    state, routing, tools and safeguards.
-   `docs/architecture/data-model.md`: ERD and entity descriptions.
-   `docs/api/`: OpenAPI and integration guides.
-   `docs/security/`: threat model, RBAC matrix, data handling and
    retention.
-   `docs/modules/`: module implementation notes and acceptance results.
-   `docs/deployment/`: environment configuration, deployment and
    rollback instructions.
-   `docs/decisions/`: ADRs.

------------------------------------------------------------------------

# 14. Initial product questions that must be confirmed

Do not silently decide these if the answer changes compliance, data
design or the product's business model:

1.  Is the target market the United States, India or another country?
2.  Is this intended to be a true MLS for licensed professionals, a
    brokerage platform, or a broader property-listing network?
3.  Which RESO data dictionary/API version and conformance requirements
    apply?
4.  Which MLS policies, Fair Housing rules and Clear Cooperation rules
    apply?
5.  What user roles and listing visibility/sharing rules does WildCatter
    expect?
6.  Are there supplied sample datasets, IDX/MLS integrations, GIS
    sources or sandbox credentials?
7.  Is a native mobile application required, or is a responsive web/PWA
    acceptable for the evaluation?
8.  Does the company mandate specific technologies or hosting services?
9.  What is the deadline, expected demo scope and evaluation rubric?
10. What repository permissions and GitHub transfer process should be
    used?

If the company does not answer immediately, document assumptions and
build only reversible foundations. Do not fabricate regulatory
requirements or proprietary integration access.

------------------------------------------------------------------------

# 15. First action: do not build the whole system at once

When this repository is first opened, Claude Code should:

1.  Read this file.
2.  Inspect the supplied company blueprint and any other specification
    files in the repository.
3.  Check whether the separate company email specification has been
    added. If not, record it as an outstanding input.
4.  Ask for or confirm the target market and mobile-app expectation if
    not already known.
5.  Propose the initial stack with trade-offs and ADRs.
6.  Implement **Module 0 only** after approval.
7.  Stop and report completion.

**The governing rule for this project is simple: complete, test,
document and approve one module before starting the next.**
