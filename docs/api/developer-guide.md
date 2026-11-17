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

## Webhooks

An administrator adds a webhook on the **Webhooks** page: an endpoint URL (https in production, on a public address) and the events to send. The signing secret (`whsec_…`) is shown once.

| Event | Sent when | `data` |
|---|---|---|
| `listing.changed` | A listing is created, edited, changes status or is archived | `subject_type`, `subject_id` |
| `property.changed` | A property is created or edited | `subject_type`, `subject_id` |
| `workflow.finished` | A listing workflow succeeds, fails or is cancelled | `subject_type`, `subject_id` (the listing), `run_id`, `status` |
| `ping` | Someone clicks "Send test" | `subscription_id` |

Each delivery is a `POST` with a JSON body:

```json
{"id": "<event id>", "type": "listing.changed", "created_at": "2026-11-17T12:00:00+00:00", "organisation_id": "…", "data": {"subject_type": "listing", "subject_id": "…"}}
```

and these headers: `X-MLS-Event` (the type), `X-MLS-Delivery` (the delivery ID, the same on every retry) and `X-MLS-Signature: t=<unix time>,v1=<hex>`. Check the signature before trusting the body:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    t = int(parts["t"])
    if abs(time.time() - t) > 300:
        return False  # too old: maybe a replay
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"t={t},v1={expected}", header)
```

Answer with any 2xx within 10 seconds. Anything else (including redirects and timeouts) is a failed attempt; the delivery is tried again after 30 s, 1, 2, 4 and 8 minutes, then marked failed. An administrator can send a failed delivery again from the delivery log. Deliveries can repeat and arrive out of order: skip duplicates by `X-MLS-Delivery`, and read the current state through the API instead of trusting the order of events.

A complete receiver is in [`examples/webhook_receiver.py`](../../examples/webhook_receiver.py).

## What is not offered yet

No OAuth client credentials, and no per-endpoint limits. Keys and webhook secrets cannot be rotated in place: create a new one, switch, then remove the old one.
