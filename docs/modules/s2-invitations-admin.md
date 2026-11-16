# Sprint 2: Invitations and admin UI (Module 1, part b)

Completed 2026-11-16. Module 1 is now complete.

## Scope delivered

- Invitations: an administrator creates an invitation for an email and role and receives a one-time link. The invited person opens it, creates an account if they have none, and joins. Pending invitations can be listed and revoked. Links expire after 7 days and work once.
- Member management: change a member's role, remove a member.
- Profile: change your name; change your password (signs out your other sessions).
- Password reset: a platform administrator issues a one-time link (24 hours). Using it sets a new password and signs the user out everywhere.
- Organisation switcher, and navigation that follows the caller's permissions in the active organisation.
- Platform page: create an organisation, issue a reset link.
- Local seed data: `python -m app.seed`.
- Tables `invitations` and `password_reset_tokens` (one migration). Only token hashes are stored.

**No email is sent.** No email provider has been chosen, so links are shown once to the administrator who created them, to pass on by any channel. This is stated in the UI.

## New endpoints

| Method and path | Access |
|---|---|
| `PATCH /api/v1/auth/me` | signed in |
| `POST /api/v1/auth/password` | signed in |
| `POST /api/v1/auth/password-reset-links` | platform admin |
| `POST /api/v1/auth/password-reset` | public; the token is the credential |
| `PATCH /api/v1/organisations/current/members/{user_id}` | `member:manage` |
| `DELETE /api/v1/organisations/current/members/{user_id}` | `member:manage` |
| `GET`, `POST /api/v1/organisations/current/invitations` | `member:manage` |
| `DELETE /api/v1/organisations/current/invitations/{id}` | `member:manage` |
| `POST /api/v1/invitations/preview` | public; the token is the credential |
| `POST /api/v1/invitations/accept` | public; the token is the credential |

`GET /api/v1/organisations/current` now also returns `my_role`, `my_permissions` and `assignable_roles`.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| One-time link token | `auth.new_token()` returns `(token, hash)`; store the hash, look up with `auth.hash_token`, fail with `auth.invalid_link()` |
| Token in a request | In the JSON body, never the URL, so it stays out of access logs |
| Show or hide UI by permission | `my_permissions` from `GET /organisations/current`; never role names |
| Form or button with busy and error state (web) | `useAction()` in `apps/web/src/api.ts` |
| Paginated list (web) | `useList(path, reloadKey)` in `apps/web/src/api.ts` |
| Active organisation (web) | `setActiveOrganisation(id)`; `api()` then sends `X-Organisation-ID` |
| Show a secret link once (web) | `OneTimeLink` component |
| New page (web) | A `<Route>` in `apps/web/src/Workspace.tsx` (signed in) or `App.tsx` (public) |

## Acceptance criteria (INSTRUCTIONS.md Module 1)

| Criterion | Result |
|---|---|
| Users can authenticate | Met (Sprint 1). |
| An administrator can create/invite users and assign roles | Met. Tested and checked live. |
| Users can only access authorised organisations and resources | Met. |
| Automated tests prove cross-tenant access is blocked | Met: `tests/test_tenancy.py`, and `test_member_management_cannot_cross_tenants` in `tests/test_members.py`. |
| API errors do not leak secrets or internal stack traces | Met. Revoked, expired, used and made-up links all get the same answer. |

Checks run locally: API `ruff format --check`, `ruff check`, `mypy` (strict), `alembic upgrade head`, `alembic check`, `pytest` (39 passed); web `eslint`, `prettier --check`, `tsc --noEmit`, `vitest` (13 passed), `vite build`. Live through `http://localhost:5173/api`: seed, invite, preview, accept with new account, sign in, role change, cross-tenant removal refused (404), reset refused for an organisation administrator (403), reset by platform administrator, old session rejected, removal, audit list.

The web screens were exercised by component tests with a stubbed API, not by hand in a browser. A browser end-to-end test arrives in Sprint 5.

## Known limitations

- No email delivery, so no self-service "forgot password". A user who forgets their password needs a platform administrator.
- A platform administrator cannot yet list or deactivate users from the UI; reset links are issued by typing the email.
- The organisation switcher lists at most 100 organisations for a platform administrator.
- Password change and the public link endpoints are not rate limited. Link tokens are 256-bit random values, so guessing is not practical.
- Expired invitations, used reset tokens and old sessions are not purged.
- If an administrator removes a member who is signed in, that member's open page shows the organisation until it is reloaded; the API refuses their requests at once.
- Not run on GitHub CI yet; nothing has been pushed.

## Next

Sprint 3: property and listing backend (Module 2, part a).
