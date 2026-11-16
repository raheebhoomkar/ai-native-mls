# Sprint 3: Property and listing backend (Module 2, part a)

Completed 2026-11-17. API only. The screens are Sprint 4.

## Scope delivered

- Tables `properties`, `listings`, `listing_status_history` (one migration).
- Property and listing are separate records. Address, rooms, area and year built live on the property; price, status, remarks, agent and visibility live on the listing. One property can have many listings.
- Create, read, update and archive for both. Archive is a soft delete.
- Status lifecycle with a single transition function, permission-gated approval, and an append-only history.
- Search with filters, four sort orders and cursor pagination.
- Optimistic concurrency: every edit and status change sends the `version` it read; a mismatch returns `409 version_conflict`.
- Money is `NUMERIC(14,2)` plus an ISO 4217 currency code. Area is `NUMERIC(12,2)` plus a unit (`sqft` or `sqm`). Both are sent and returned as strings, never floats.
- Audit events for every create, update, status change and archive. A listing update records which fields changed, with old and new values (remarks: only that they changed).

## Status lifecycle

| From | May become |
|---|---|
| `draft` | `pending_review`, `withdrawn` |
| `pending_review` | `active` (needs `listing:publish`), `draft`, `withdrawn` |
| `active` | `temporarily_off_market`, `sold`, `withdrawn`, `expired` |
| `temporarily_off_market` | `active`, `withdrawn`, `expired` |
| `withdrawn`, `expired` | `draft` |
| `sold` | nothing; final, and no longer editable |

Marking sold requires a sold price in the listing's currency. It is recorded as reported by the agent, not as a verified transaction price.

Defined in `TRANSITIONS` in `app/modules/listings/service.py`. Every status change goes through `transition_listing`; the publication checks planned for Sprint 16 attach there.

## Visibility policy

Defined in `_visible` in the same file; every read query uses it.

- A listing is always visible to members of the organisation that owns it.
- A listing with `visibility: "network"` is also visible, read-only, to members of every other organisation, but only while its status is `active`, `temporarily_off_market` or `sold` and it is not archived.
- `visibility: "private"` (the default) is never visible outside the owning organisation.
- Other organisations cannot see a shared listing's status history, and cannot open or reuse its property record directly.
- A listing the caller cannot see returns 404. One they can see but not change returns 403.

Properties are owned by the organisation that created them and are not shared.

**This policy is an assumption, not a company requirement** (INSTRUCTIONS.md §14 question 5). Sharing with one named organisation is not built; it is planned with collaboration in Sprint 19.

## Endpoints

| Method and path | Access |
|---|---|
| `POST /api/v1/properties` | `listing:write` |
| `GET /api/v1/properties`, `GET /api/v1/properties/{id}` | `listing:read`, own organisation |
| `PUT /api/v1/properties/{id}` | `listing:write` |
| `DELETE /api/v1/properties/{id}` | `listing:write`; refused while it has unarchived listings |
| `POST /api/v1/listings` | `listing:write` |
| `GET /api/v1/listings`, `GET /api/v1/listings/{id}` | `listing:read`, per visibility policy |
| `PATCH /api/v1/listings/{id}` | `listing:write`, and listing agent or `listing:manage_all` |
| `POST /api/v1/listings/{id}/transitions` | as above; approval also needs `listing:publish` |
| `DELETE /api/v1/listings/{id}` | as above; live listings must be withdrawn first |
| `GET /api/v1/listings/{id}/history` | `listing:read`, owning organisation only |

Listing search parameters: `scope` (`all`, `organisation`, `network`), `status` (repeatable), `listing_type`, `property_type`, `city`, `locality`, `min_price`, `max_price`, `min_bedrooms`, `listing_agent_user_id`, `q` (title, locality or city), `include_archived`, `sort` (`newest`, `oldest`, `price_asc`, `price_desc`), `limit`, `cursor`.

Each listing in a response carries `can_edit` and `allowed_transitions` for the caller, so the UI does not re-implement the rules.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Read a listing the caller may see | `listings.service.get_listing(session, ctx, id)` |
| Change a listing's status | `listings.service.transition_listing`; never set `status` directly |
| Editable record | `version` column with `__mapper_args__ = {"version_id_col": version}`, check the client's version, flush with `_flush` |
| Fixed-choice text column | `one_of(column, values)` from `app/core/db.py` in a `CheckConstraint` |
| Sort by a decimal column | `paginate` now accepts `Decimal` sort keys |
| Timestamp that must order rows | Set it in Python; `now()` in Postgres is the transaction start time |

## Acceptance criteria (INSTRUCTIONS.md Module 2)

| Criterion | Result |
|---|---|
| An authorised agent can create and edit a listing | Met through the API. Screens: Sprint 4. |
| A listing is linked to the correct property, agent and brokerage | Met. |
| Invalid status transitions are rejected | Met. |
| Listing history is visible to authorised users | Met; owning organisation only. |
| Search and filters work against persisted data | Met. |
| Role and tenant permissions are tested | Met: `tests/test_listings.py`. |
| Build desktop listing table, detail and forms; responsive | **Not in this sprint.** Sprint 4. |

Checks run locally: `ruff format --check`, `ruff check`, `mypy` (strict), `alembic upgrade head`, `alembic check`, `pytest` (55 passed); web suite re-run unchanged (13 passed). Live against the running API with seeded accounts: create property and listing, submit, agent self-approval refused (403), admin approval, other organisation sees the shared live listing read-only, edit 403, history 403, stale version 409, search, history.

Bugs found by tests and the live check, fixed:

- The search rejected `limit` and `cursor`, because the filter model forbade unknown query parameters.
- History rows written in one transaction shared a timestamp, so their order was arbitrary.
- A create response showed `25000000` where a later read showed `25000000.00`.

## Known limitations

- No screens yet.
- Two requests that pass the version check at the same instant are separated by the database (`version_id_col`), returning 409 to the loser. That path is implemented but has no automated test, since it needs two concurrent transactions.
- Listings do not expire by themselves on `expires_on`; someone must set `expired`. A scheduled job can do it once the worker exists (Sprint 6).
- Editing an active listing does not send it back to review.
- An unknown query parameter is ignored, not rejected.
- `q` is a substring match, not full-text or semantic search (Sprint 13).
- A property has no duplicate detection: the same address can be entered twice.
- No media, coordinates or map (Sprints 6 and 12).
- Changing `sort` or filters while following a cursor gives undefined results.
- Not run on GitHub CI yet.

## Next

Sprint 4: listing UI (Module 2, part b).
