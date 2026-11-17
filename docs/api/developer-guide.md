# Public API developer guide

The AI-Native MLS API is the same HTTP API the web app uses. Third-party clients (a CRM, a portal feed, a script) reach it with an API key. Every endpoint, with its request and response schema, is in the OpenAPI document at `/api/v1/openapi.json` and the interactive docs at `/api/v1/docs` (both turned off in production; use a local copy of the app to browse them).

A runnable example is in [`examples/mls_client.py`](../../examples/mls_client.py) (Python, standard library only).

## Getting a key

An administrator of the organisation (brokerage admin or MLS admin) opens **API keys** in the web app, names the key, picks its scopes and its rate limit, and copies the key. The key is shown once. Only its SHA-256 is stored, so a lost key cannot be recovered; revoke it and make a new one.

| Scope | Allows |
|---|---|
| `listing:read` | Read listings, properties, photos, policy checks, valuations, workflows and the other listing data the creator may read |
| `listing:write` | Create properties and listings, edit, upload photos, change status, start workflows and checks, as far as the creator may |

A key acts as the administrator who created it, in that organisation only, and never with more than its scopes. If that person leaves the organisation, every key they made stops working (401). Members, invitations, the audit log, jobs and API keys themselves cannot be reached with a key. Approving listings is not a scope: a person approves.

## Calling the API

```bash
curl -H "Authorization: Bearer $MLS_API_KEY" https://<host>/api/v1/listings?limit=10
```

- Send the key as `Authorization: Bearer <key>`. No cookie and no `X-Organisation-ID` are needed; the key fixes the organisation. A different `X-Organisation-ID` is refused (403).
- Every response carries `X-Request-ID`. Send your own (letters, digits, `-`, `_`, `.`) to follow one request through the server's logs, background jobs and audit events.
- Errors always look like this:

```json
{"error": {"code": "rate_limited", "message": "This key allows 60 requests a minute. Try again shortly.", "request_id": "…", "details": []}}
```

| Status | Code | Meaning |
|---|---|---|
| 401 | `invalid_api_key` | Unknown, revoked, or its creator left the organisation |
| 403 | `forbidden` | The key's scopes or its creator's role do not allow this |
| 404 | `not_found` | Does not exist, or is not visible to this organisation |
| 409 | various | A conflict, for example `version_conflict` (someone edited first) or `workflow_in_progress` |
| 422 | `validation_error`, `idempotency_key_reused` | The request is wrong; `details` names the fields |
| 429 | `rate_limited` | Too many requests this minute; wait `Retry-After` seconds |

## Rate limits

Each key has a limit per rolling minute (1 to 600, default 60), set when it is created. Over the limit the API answers 429 with `Retry-After: 60`. Requests refused for any reason still count. The **API keys** page shows each key's use in the last minute and when it was last used; every request is logged with its method, path, status, request ID and IP address.

## Idempotent writes

Network failures leave a client unsure whether a write happened. Send an `Idempotency-Key` header (1–200 characters; a UUID is ideal) on `POST`, `PUT`, `PATCH` and `DELETE`:

- The first request runs, and its answer (status and body) is stored for 24 hours.
- Sending the same key with the same method, URL and body again returns the stored answer, with `Idempotent-Replayed: true`, and does nothing else.
- The same key with a different request: 422 `idempotency_key_reused`.
- While the first request is still running: 409 `idempotency_in_progress`.
- A server error (5xx) is not stored, so the client may retry with the same key.
- Keys are separate per credential: two clients cannot see each other's answers.

Use a new key for every new write, and the same key for every retry of that write.

## Paging

Lists return `{"items": [...], "next_cursor": "..."}`. Pass `cursor=<next_cursor>` to get the next page, with the same filters and sort. `limit` is at most 100.

## Optimistic concurrency

Editable records carry a `version`. Send the version you read when you edit or change status; if someone changed the record since, the API answers 409 `version_conflict`. Read it again and retry.

## What is not offered yet

No webhooks yet (planned in Sprint 18), no OAuth client credentials, and no per-endpoint limits. Keys cannot be rotated in place: create a new one, switch, then revoke the old one.
