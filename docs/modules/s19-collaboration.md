# Sprint 19: Collaboration (Module 12)

**Status: done (2026-11-17).** Committed at the end of the sprint. This closes Phase C; the Phase C report is at the end of this file.

Branch: `feature/s6-media-jobs`.

Scope (from the approved plan): assignment, comments and private notes with visibility rules, notifications and preferences, an activity timeline, conflict detection UI on `version` mismatch.

## Design decisions (reversible; made 2026-11-17)

- **Module** `app/modules/collaboration/`. Tables `listing_assignments`, `listing_comments`, `notifications`, `notification_preferences` (migration `a2ad1283f4b1`).
- **Only the organisation that owns a listing** sees its assignment, comments and timeline. Another organisation gets 404, even when the listing is shared with the network.
- **Assignment:** one assignee per listing besides the listing agent; set or cleared by the listing's editors; the assignee must be a member who works on listings (not `api_consumer`). Audited as `listing.assigned`; the assignee is notified.
- **Comments:** `team` (everyone in the organisation who can read the listing) or `private` (a note only its author sees, never notified). Writing needs `listing:write`. Only the author edits or deletes; a deleted comment keeps its row with the text cleared, so the timeline still shows that something was said.
- **Notifications** (in the app only; no email yet): `assigned`; `comment` (to the listing agent, the assignee and earlier commenters, never the author); `workflow_finished` (to whoever started the run, from the S18 `workflow.finished` outbox event). People who left the organisation are skipped. **Preferences:** each kind on or off per person; on by default.
- **Activity timeline:** `audit.list_for_listing` (events that target the listing, and those that name it in `detail.listing_id`, such as policy checks) merged with the comments the caller may see, newest first, with a plain-language summary per action.
- **Conflict UI:** when a listing save is refused with `version_conflict`, the edit page now loads the saved version and shows a table of the fields that differ (yours versus theirs). "Save mine over theirs" saves the typed values on top of the new version; "Use theirs and discard mine" loads theirs. Nothing is overwritten without a click. The property form keeps the simpler reload notice.
- **Web:** a "Team" section on the listing page (assignment, comments and notes, activity), a "Notifications" link with the unread count (refreshed every 30 s) and a Notifications page with "Mark as read", "Mark all as read" and the preferences.

## Chunks

- [x] **1. Backend.** Models, migration, service, API, tests (`tests/test_collaboration.py`, 6).
- [x] **2. Web.** `ListingCollaboration.tsx`, `Notifications.tsx`, the conflict panel in `ListingForm.tsx`; tests (`ListingCollaboration.test.tsx` 1, `Notifications.test.tsx` 2, two conflict tests in `ListingPages.test.tsx`).
- [x] **3. Phase C end-to-end test** (`e2e/workflow.e2e.ts`), run against the dev stack and the production image; Dockerfile and CI fixes found on the way; docs.

## Acceptance results

- Assignment notifies the assignee only; editors only; only members who work on listings (`test_assignment_notifies_the_assignee`).
- Team comments reach the team, private notes only their author; read-only members read but cannot write; another organisation gets 404 on a shared listing (`test_team_comments_and_private_notes`).
- Only the author edits or deletes (`test_only_the_author_edits_or_deletes`).
- A muted kind is not delivered; read marks work and are per person (`test_preferences_mute_a_kind_and_read_marks`).
- The timeline merges status changes, edits, workflow and policy-check events with comments, newest first, and hides others' private notes (`test_activity_timeline_merges_events_and_comments`).
- A finished workflow notifies whoever started it (`test_finished_workflow_notifies_whoever_started_it`).
- A conflict shows both versions and lets the user keep theirs or their own (web tests).
- All checks pass: API ruff, mypy, alembic check, pytest (334); web lint, typecheck, test (79), build; Playwright (2 journeys) against the dev stack and against the production Docker image.

## Known limitations

- No email or push notifications; in the app only. No @mentions.
- One assignee per listing; the history of assignments is in the audit log only.
- The conflict table compares listing details only, not the property form.
- The timeline shows the 100 newest events.

## Phase C report (S15–S19)

### What works end to end

- **Workflow:** one click runs locate, read photos, policy check, human review, search index and valuation as a LangGraph graph whose runs and steps are saved. Steps are idempotent; errors are retried within a budget; one trace ID follows a request into every job and AI call.
- **Human review and the publication gate:** the run pauses while photo suggestions or policy findings wait for a person, and goes on by itself after each decision. A listing cannot be approved while its workflow is unfinished; the check lives in the listing service, so no route, import or script can skip it.
- **Monitor:** runs with cancel and retry; failed background jobs with retry for administrators.
- **Public API:** API keys with scopes and per-key rate limits, a usage log, idempotent writes, a developer guide and a sample client.
- **Webhooks:** signed events (listing, property, workflow finished) with retries, a delivery log, test pings and an SSRF guard; a sample receiver.
- **Collaboration:** assignment, team comments and private notes, notifications with preferences, an activity timeline, and a conflict screen that compares versions.
- Verified each sprint against the real API and worker on the seeded database, and at the end with the Playwright journeys against the production image.

### Fixed on the way (worth knowing)

- **Deploy breaker:** LangGraph pulls in `zstandard`, which has no Python 3.15 wheel; the slim image has no compiler, so `docker build` failed. The Dockerfile now builds wheels in a separate stage with gcc; the final image has no compiler.
- **CI end-to-end job:** it did not pass `MEDIA_SIGNING_KEY` (required in production since S6), so the container would not start. Fixed with a throwaway 32+ character key.
- A step could wait for ever on an AI run whose job died on an old worker; it now fails with the job's error.

### Deferred

- Email notifications, @mentions, service-account API keys, key and secret rotation, daily quotas, webhook auto-disable, paging on the monitor.
- Waking a waiting workflow step directly from the work it waits for (it polls every 10 s).
- Cleanup jobs for idempotency records and old usage rows (fits S21 hardening).

### Open risks

- **Not deployed yet.** S5's go-live step (push and create the Render Blueprint) is still open, so nothing in Phases B and C has run on Render. The image builds and passes both journeys locally.
- **Restart workers after every deploy.** A worker running older code fails jobs of kinds it does not know (seen twice in this phase). The single-container deploy restarts both together, which is safe; a separate worker service would need the same.
- **Gemini quota and outages:** a real run hit HTTP 503 ("high demand"). The workflow records the failure and the other steps finish, but a demo with the real key can show failed extraction steps at busy times.
- `.env` already holds a Gemini key, so local runs without `GEMINI_API_KEY=` in front call Gemini.

### Recommended changes to the remaining sprints

- Do the S5 go-live before S20, so S20–S22 ship to a live URL as planned.
- S21: add the cleanup jobs above, the dead-letter view for webhook deliveries, and an alert when a worker meets an unknown job kind.
- S20: put the Monitor, Notifications, API keys and Webhooks pages on the role-aware dashboard.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Tell a person something | `collaboration.service.notify(session, user_ids, organisation_id=..., kind=..., title=...)`; add the kind to `NOTIFICATION_KINDS` (a migration changes the check constraint) |
| Everything that happened to a listing | `audit.list_for_listing`, or `collaboration.service.activity` with comments |

## Next

Phase C is complete. Stop for the Phase C report and the developer's feedback before Phase D (S20 UX and admin console).
