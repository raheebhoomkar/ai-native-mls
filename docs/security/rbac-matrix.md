# Roles and permissions

Source of truth: `services/api/app/modules/organisations/permissions.py`. Update this page in the same change as that file.

## Model

- An **organisation** is the tenant (kind `mls` or `brokerage`). Tenant-owned records carry `organisation_id`.
- A **membership** links a user to an organisation with exactly one role.
- A user may belong to several organisations, with a different role in each.
- **Platform administrator** is a flag on the user, not a membership role. It grants every permission in every organisation.
- Routes ask for a permission with `require("...")`. They never test role names.

## Matrix (Sprint 3)

| Permission | Platform admin | MLS admin | Brokerage admin | Broker | Agent | API consumer |
|---|---|---|---|---|---|---|
| `organisation:read` — view the active organisation | yes | yes | yes | yes | yes | yes |
| `member:read` — list members (name, email, role) | yes | yes | yes | yes | yes | no |
| `member:manage` — invite, revoke invitations, change roles, remove members | yes | yes | yes | no | no | no |
| `audit:read` — view the organisation's audit log | yes | yes | yes | no | no | no |
| `listing:read` — see own organisation's listings and properties, and listings shared by others | yes | yes | yes | yes | yes | yes |
| `listing:write` — create properties and listings; edit, transition and archive listings you are the agent of | yes | yes | yes | yes | yes | no |
| `listing:manage_all` — do the same for any listing in the organisation; assign the listing agent | yes | yes | yes | yes | no | no |
| `listing:publish` — approve a listing pending review | yes | yes | yes | yes | no | no |
| Create an organisation (platform-level, not tenant-scoped) | yes | no | no | no | no | no |
| Issue a password reset link (platform-level) | yes | no | no | no | no | no |

Listing visibility between organisations is described in `docs/modules/s3-listings-backend.md`.

Listing photos add no permission of their own. Whoever may read a listing may see its photos; whoever may edit it (`listing:write` as its agent, or `listing:manage_all`) may upload, remove and retry them, and only while it is not archived. Photo files are fetched through signed links that expire after 15 minutes; see `docs/modules/s6-media-jobs.md`.

AI photo extraction adds no permission of its own either. Whoever may edit a listing may request an extraction (`POST /listings/{id}/ai/extractions`); whoever may read it may list its runs. Runs only suggest values and never change the listing. See `docs/modules/s7-ai-extraction.md`.

Reviewing AI suggestions adds no permission either. Whoever may edit the listing may accept, edit or reject a suggestion (`POST /ai/runs/{id}/decisions`); each decision is final and audited. Accepted or edited values become listing features, never listing fields. Whoever may read the listing may see the decisions and its confirmed features (`GET /listings/{id}/features`). Another organisation gets 404. See `docs/modules/s8-ai-review.md`.

## Role assignment rules

- An MLS organisation may hold: MLS administrator, broker, agent, API consumer.
- A brokerage may hold: brokerage administrator, broker, agent, API consumer.
- Nobody can change their own role or remove themselves. Since only an administrator can change roles, an organisation that has an administrator cannot lose its last one except by a platform administrator's action.
- Organisation administrators cannot reset passwords. A user may belong to several organisations, so a reset by one organisation's administrator would give access to the others.
- An invitation link adds a membership to the invited email's account. It never signs anyone in and never changes an existing account's password.
- Removing a member deletes the membership, not the user account.

## Tenant scoping rules

1. The active organisation comes from the `X-Organisation-ID` header, or from the user's only membership when the header is absent.
2. A user with zero or several memberships and no header gets `400 organisation_required`.
3. A non-member gets `403 forbidden`. The response is identical for an organisation that does not exist, so IDs cannot be probed.
4. Every such denial writes an `access.denied` audit event.
5. Services receive a `TenantContext` and filter by its `organisation_id`. They never take an organisation ID from the request body.

## Audited actions

`auth.login`, `auth.login_failed`, `auth.logout`, `auth.password_changed`, `auth.password_reset_issued`, `auth.password_reset_completed`, `access.denied`, `organisation.created`, `user.created`, `user.profile_updated`, `invitation.created`, `invitation.revoked`, `invitation.accepted`, `member.role_changed`, `member.removed`, `property.created`, `property.updated`, `property.archived`, `listing.created`, `listing.updated`, `listing.status_changed`, `listing.archived`, `media.uploaded`, `media.deleted`, `ai.extraction_requested`, `ai.suggestion_decided`.

Audit events record actor, organisation, target, IP address, request ID and time. They never contain passwords, session tokens or link tokens.

## Not confirmed by the company

The role list comes from INSTRUCTIONS.md §5. Which roles may do what, and how listings are shared between organisations, is still an open question (§14 question 5). The matrix above is a reversible assumption.
