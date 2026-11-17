# Sprint 16: Review gate and monitor (Module 10b)

**Status: done (2026-11-17).** Committed at the end of the sprint.

Branch: `feature/s6-media-jobs`.

Scope (from the approved plan): human-review pause and resume, a publication gate that cannot be bypassed, cancel and retry controls, a job monitor UI, status updates to the frontend.

## Design decisions (reversible; made 2026-11-17)

- **Workflow v2** adds a `review` step: `geocode, extract, compliance, review, index, valuation`. A LangGraph conditional edge after `review` ends the pass ("pause") until the review step has finished, so index and valuation run only after people have decided. Runs of v1 have no review row; the node reports it skipped.
- **Pause:** the review step waits while the extraction's review task is open (undecided photo suggestions) or while `compliance.ensure_approvable` refuses (policy findings open or confirmed). The run goes to `awaiting_review` and no next pass is queued.
- **Resume:** the routers that record decisions (photo suggestions, finding decisions, appeals, appeal rulings) call `workflow.wake(session, listing_id)`, which queues a pass and gives the run a fresh machine budget (passes and deadline), because time spent waiting for a person is not the machine's.
- **Publication gate:** `listings.service.APPROVAL_GUARDS`, run inside `transition_listing` (the one place a status changes) on approval (`pending_review` to `active`). Compliance registers `ensure_approvable` (moved there from the router); the workflow registers `ensure_no_open_run`: no approval while a run is queued, running, waiting or awaiting review (409 `workflow_in_progress`). A test calls the service directly to prove the router is not the only check.
- **Cancel** (`POST /workflows/{id}/cancel`): any unfinished run, by an editor of the listing. Agent runs it started carry on.
- **Retry** (`POST /workflows/{id}/retry`): a failed or cancelled run, when no other run is active on the listing. Finished and skipped steps are kept; failed steps start over (a new agent run); waiting steps keep waiting on their agent run.
- **Dead jobs:** a step waiting on an agent run whose job failed without updating the run (for example, a worker running older code) now fails with the job's error, and the compliance step never reuses such a scan. Found during the real-stack check.
- **Monitor:** `GET /workflows?status=` (a run status or `active`) lists the organisation's 50 newest runs for anyone who can read listings. `GET /jobs?status=` and `POST /jobs/{id}/retry` are for holders of `audit:read` (administrators), since job errors can name internal details; platform jobs are not shown.
- **Status updates to the frontend:** polling every `POLL_MS` while something is active (listing section and monitor), as the other sections do. No websockets.
- Audited: `workflow.cancelled`, `workflow.retried`, `job.retried`.

## Chunks

- [x] **1. Backend.** Review step and pause, wake, gate registry, cancel, retry, monitor and jobs endpoints, dead-job handling, tests (`tests/test_workflow.py`, 13 in all).
- [x] **2. Web.** "Cancel run" and "Retry run" on the listing's Workflow section, a note while awaiting review, the "Monitor" page in the nav (runs with a status filter, cancel and retry; failed jobs with retry for administrators). Tests (`Monitor.test.tsx`, 2; `ListingWorkflow.test.tsx`, 3).
- [x] **3. Real-stack check and docs.**

## Acceptance results

- Photo suggestions pause the run; deciding them resumes it to the end (`test_run_goes_through_every_step_and_carries_the_trace`).
- Policy findings pause the run; dismissing them resumes it (`test_policy_findings_pause_the_run_until_decided`).
- Approval is refused while the run is queued and while it waits for review, and allowed after (`test_approval_waits_for_the_workflow_and_its_review`); also when the service is called directly (`test_gate_holds_outside_the_router_too`).
- Cancel and retry, with permission and state checks and audit (`test_cancel_then_retry_keeps_finished_steps`).
- Monitor filters, tenant isolation, job listing and retry for administrators only (`test_monitor_lists_runs_and_failed_jobs`, `test_admin_retries_a_failed_job`).
- Real stack (API and worker on the seeded database, demo providers): on "[Demo] 2 BHK to let near the IT park" a run paused for review; its compliance step failed on a scan left behind by an old worker; cancel, then retry, started a new scan; the run paused again for the photo suggestions and policy findings; after rejecting the suggestions and dismissing the findings it resumed by itself and finished every step.
- All checks pass: API ruff, mypy, alembic check, pytest (314); web lint, typecheck, test (73), build.

## Known limitations

- A run that waits for review never times out; it waits until someone decides or cancels it.
- Wake is called from the decision routers; a decision recorded some other way (for example a script) does not wake the run until the next decision or a retry.
- Cancelling a run does not cancel agent runs it already started.
- The monitor shows the 50 newest runs and the 100 newest jobs; no paging yet.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Block approval on a new condition | append a `(session, listing_id) -> None` that raises `AppError` to `listings.service.APPROVAL_GUARDS` |
| Let a paused run go on after a decision | `workflow.service.wake(session, listing_id)` |
| Cancel or retry a run | `workflow.service.cancel`, `retry` |

## Next

S17: public API access (API keys with scopes, per-key rate limits and usage logs, idempotency keys, developer guide, sample client).
