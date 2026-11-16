# Roles and permissions

Source of truth: `services/api/app/modules/organisations/permissions.py`. Update this page in the same change as that file.

## Model

- An **organisation** is the tenant (kind `mls` or `brokerage`). Tenant-owned records carry `organisation_id`.
- A **membership** links a user to an organisation with exactly one role.
- A user may belong to several organisations, with a different role in each.
- **Platform administrator** is a flag on the user, not a membership role. It grants every permission in every organisation.
- Routes ask for a permission with `require("...")`. They never test role names.

## Matrix (Sprint 1)

| Permission | Platform admin | MLS admin | Brokerage admin | Broker | Agent | API consumer |
|---|---|---|---|---|---|---|
| `organisation:read` — view the active organisation | yes | yes | yes | yes | yes | yes |
| `member:read` — list members (name, email, role) | yes | yes | yes | yes | yes | no |
| `audit:read` — view the organisation's audit log | yes | yes | yes | no | no | no |
| Create an organisation (platform-level, not tenant-scoped) | yes | no | no | no | no | no |

Later sprints add permissions here (member management in Sprint 2, listings in Sprint 3).

## Tenant scoping rules

1. The active organisation comes from the `X-Organisation-ID` header, or from the user's only membership when the header is absent.
2. A user with zero or several memberships and no header gets `400 organisation_required`.
3. A non-member gets `403 forbidden`. The response is identical for an organisation that does not exist, so IDs cannot be probed.
4. Every such denial writes an `access.denied` audit event.
5. Services receive a `TenantContext` and filter by its `organisation_id`. They never take an organisation ID from the request body.

## Audited actions (Sprint 1)

`auth.login`, `auth.login_failed`, `auth.logout`, `access.denied`, `organisation.created`, `user.created`.

Audit events record actor, organisation, target, IP address, request ID and time. They never contain passwords or session tokens.

## Not confirmed by the company

The role list comes from INSTRUCTIONS.md §5. Which roles may do what, and how listings are shared between organisations, is still an open question (§14 question 5). The matrix above is a reversible assumption.
