# Sprint 17: Public API access (Module 11a)

**Status: done (2026-11-17).** Committed at the end of the sprint.

Branch: `feature/s6-media-jobs`.

Scope (from the approved plan): API keys with scopes, per-key rate limits and usage logs, idempotency keys on writes, a developer guide, a sample third-party client.

## Design decisions (reversible; made 2026-11-17)

- **Module** `app/modules/apikeys/` (models, service, router, middleware). Tables `api_keys`, `api_key_usage`, `idempotency_records` (migration `9a7d38c1ba0d`).
- **A key acts as the administrator who created it**, in that organisation, with that person's current role limited to the key's scopes (`TenantContext.scopes`; `permissions` is the intersection). Scopes: `listing:read`, `listing:write`. If the creator leaves, the key gives 401. Platform-administrator powers never pass through a key.
- **Key format** `mls_<8 hex>_<43 url-safe chars>`. Only the SHA-256 of the whole key is stored; the first part (`prefix`) is shown so people can tell keys apart. Created, listed and revoked by holders of `member:manage`, never with a key. Audited: `api_key.created`, `api_key.revoked`.
- **Where keys work:** only the endpoints scoped to an organisation (`_tenant_scope` reads `Authorization: Bearer`). Endpoints for people (sign-in, profile, platform admin) still need the cookie, so a key gets 401 there.
- **Rate limit:** per key, requests in the last rolling minute counted from the usage log (default 60, 1–600). Over it: 429 `rate_limited` with `Retry-After: 60`. `AppError` can now carry response headers for this. A `shortcut:` comment notes that parallel bursts can slip a few over.
- **Usage log:** a middleware writes one row per keyed request after the response, in its own transaction (method, path, status, request ID, IP). No foreign keys, so the log outlives the key and survives failed requests.
- **Idempotency:** the same middleware handles `Idempotency-Key` on POST, PUT, PATCH and DELETE for any signed-in caller (key or cookie). The record is claimed first (unique per credential hash and key), so a parallel duplicate gets 409; the answer is stored after the response; a 5xx is dropped so the client may retry; a different request with the same key gets 422; records count for 24 hours.
- **Developer guide** `docs/api/developer-guide.md`; **sample client** `examples/mls_client.py` (standard library; bearer key, waits on 429 and 5xx using `Retry-After`, an idempotency key on every write).
- **Web:** "API keys" page for administrators: create (name, scopes, rate), the key shown once, the list with use this minute and last use, revoke.

## Chunks

- [x] **1. Backend.** Models, migration, key auth in the tenant scope, rate limit, usage and idempotency middleware, API, tests (`tests/test_api_keys.py`, 6).
- [x] **2. Guide and sample client.**
- [x] **3. Web.** `ApiKeys.tsx`, `ApiKeys.test.tsx` (1).
- [x] **4. Real-stack check and docs.**

## Acceptance results

- A key is shown once and stored only as a hash; only administrators manage keys; unknown scopes are refused (`test_admin_creates_a_key_shown_once`).
- A read-only key cannot write; a write key can; keys cannot reach key management or `/auth/me` (`test_key_acts_as_its_creator_within_its_scopes`).
- Unknown, revoked and orphaned keys get 401 (`test_bad_revoked_and_orphaned_keys_are_refused`).
- The limit gives 429 with `Retry-After`; every request is logged with its status and request ID (`test_rate_limit_and_usage_log`).
- A repeated write returns the first answer and creates nothing; a changed body with the same key is refused; keys are separate per caller (`test_idempotency_key_replays_the_first_answer`, `test_failed_writes_are_stored_but_server_errors_are_not`).
- Real stack: a key with a limit of 5 listed listings and created a property and a listing through `examples/mls_client.py`; the third quick request got 429, and the client waited the 60 s and then succeeded.
- All checks pass: API ruff, mypy, alembic check, pytest (320); web lint, typecheck, test (74), build.

## Known limitations

- A key acts as a person; there are no service accounts yet.
- No in-place rotation; create a new key, switch, revoke the old one.
- The rate limit is per minute only, with no daily quota, and parallel bursts can slip a few over it.
- Idempotency records older than 24 hours are removed only when the same key comes again; a cleanup job belongs in S21.
- The usage log is not shown row by row in the app; it is in the `api_key_usage` table.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Know whether a request came with a key | `ctx.scopes is not None` |
| An error with response headers | `AppError(..., headers={...})` |

## Next

S18: webhooks (subscriptions, HMAC-signed deliveries from the outbox, retries with backoff, delivery log).
