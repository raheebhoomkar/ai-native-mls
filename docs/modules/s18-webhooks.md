# Sprint 18: Webhooks (Module 11b)

**Status: done (2026-11-17).** Committed at the end of the sprint.

Branch: `feature/s6-media-jobs`.

Scope (from the approved plan): subscriptions, HMAC-signed deliveries from the outbox, retries with backoff, a delivery log.

## Design decisions (reversible; made 2026-11-17)

- **Module** `app/modules/webhooks/`. Tables `webhook_subscriptions` and `webhook_deliveries` (migration `6f12761284bd`).
- **Events:** `listing.changed`, `property.changed` (already in the S13 outbox) and the new `workflow.finished` (emitted whenever a run ends: succeeded, failed or cancelled, with `run_id` and `status`). Events are thin: type, IDs and status; the receiver reads details through the API.
- **Flow:** the outbox gives each event a `webhooks.fanout` job, which makes one delivery row per active matching subscription (unique per subscription and event, so a repeated fan-out adds nothing) and queues a `webhooks.deliver` job. The body is fixed when the delivery is made, so every attempt sends the same bytes.
- **Retries are ours, not the job queue's:** the deliver job never raises; it records the attempt (status code, error, start of the answer) and queues the next attempt after 30 s, 1, 2, 4 and 8 minutes. After 6 attempts the delivery fails. "Send again" resets it with a fresh set of attempts.
- **Signing:** `X-MLS-Signature: t=<unix time>,v1=<hex HMAC-SHA256(secret, "<t>." + body)>`, plus `X-MLS-Event` and `X-MLS-Delivery`. Receivers should refuse signatures older than 5 minutes. `webhooks.service.verify` is the reference check and is tested; `examples/webhook_receiver.py` does the same with the standard library. The secret (`whsec_…`) is stored as is, because signing needs it, and shown once.
- **SSRF guard:** in production only `https` URLs whose every resolved address is public are accepted, checked when the webhook is made and again before every attempt; redirects are not followed. Outside production `http` and local addresses are allowed, for local receivers.
- **Who:** people with `member:manage` (administrators), not API keys. Another organisation gets 404. Audited: `webhook.created`, `webhook.disabled`, `webhook.redelivered`.
- **Web:** "Webhooks" page: add (URL, events), the secret shown once, "Send test" (a signed `ping`), "Turn off", and each webhook's delivery log with "Send again".

## Chunks

- [x] **1. Backend.** Models, migration, fan-out, delivery with retries, signing, SSRF guard, API, `workflow.finished` event, tests (`tests/test_webhooks.py`, 8).
- [x] **2. Web.** `Webhooks.tsx`, `Webhooks.test.tsx` (1).
- [x] **3. Sample receiver, guide, real-stack check, docs.**

## Acceptance results

- A listing change reaches the endpoint once, signed so the reference check accepts it (`test_listing_change_is_delivered_signed`).
- Only subscribed events are sent; `workflow.finished` carries the run's status (`test_only_subscribed_events_are_sent`).
- A failing endpoint is tried 6 times with growing waits, then marked failed; "send again" delivers the same body (`test_failed_endpoint_is_retried_with_backoff_then_redelivered`); a timeout counts as a failed attempt (`test_network_error_counts_as_a_failed_attempt`).
- A turned-off webhook gets nothing, and its pending deliveries fail (`test_disabled_webhook_gets_nothing`).
- Only administrators, not keys, manage webhooks; other organisations get 404; bad events and schemes are refused (`test_only_people_who_administer_manage_webhooks`).
- Production refuses http, loopback and private addresses (`test_production_refuses_plain_http_and_private_addresses`).
- Tampered, wrongly keyed and old signatures are refused (`test_signature_check_refuses_tampering_and_old_messages`).
- Real stack: `examples/webhook_receiver.py` on port 9099 got a test ping and a `workflow.finished` event from a real run, and accepted both signatures; both deliveries show "Delivered", 1 attempt, HTTP 204.
- All checks pass: API ruff, mypy, alembic check, pytest (328); web lint, typecheck, test (75), build.

## Known limitations

- Deliveries may repeat (at least once) and may arrive out of order; receivers should skip duplicates by `X-MLS-Delivery` or the event `id`.
- The secret cannot be rotated in place; add a new webhook and turn the old one off.
- A webhook that keeps failing is not turned off on its own.
- The delivery log shows the 50 newest deliveries per webhook; failed deliveries also show on the S16 Monitor only as webhook jobs, not as deliveries.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Offer a new event to webhooks | emit it with `outbox.emit` and add its kind to `webhooks.service.EVENT_KINDS` |
| Check a signature (tests, docs) | `webhooks.service.sign`, `verify` |

## Next

S19: collaboration (assignment, comments and private notes with visibility rules, notifications and preferences, activity timeline, conflict detection UI).
