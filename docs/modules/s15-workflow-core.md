# Sprint 15: Workflow core (Module 10a)

**Status: done (2026-11-17).** Committed at the end of the sprint, as the developer asked for Phase C.

Branch: `feature/s6-media-jobs`.

Scope (from the approved plan): a LangGraph graph over the existing S7–S14 steps, typed state, persisted runs and steps, idempotent step execution, bounded retries and budgets, a trace ID from the request to the agent call.

## Design decisions (reversible; made 2026-11-17)

- **Module** `app/modules/workflow/`. Workflow `listing_intake` v1, steps in order: `geocode`, `extract`, `compliance`, `index`, `valuation`. LangGraph `StateGraph` with typed state (`run_id`, and each step's status merged with `operator.or_`). Compiled once (`GRAPH`).
- **Persistence is ours, not LangGraph's checkpointer.** `workflow_runs` and `workflow_steps` (unique per run and step name). Every pass rebuilds the state from these rows, so a pass that dies half way is simply run again.
- **One pass is one `workflow.advance` job.** The run row is locked (`FOR UPDATE`) so two passes never overlap. A step returns `succeeded`, `skipped`, `failed` or `waiting`. While any step is pending or waiting, the run is `waiting` and the next pass is queued 10 s later (polling; a `shortcut:` comment says when to change it).
- **Steps reuse the existing services**, acting as the person who started the run with the role they have now (if they left the organisation, the run fails):
  - `geocode`: waits for the S12 geocode; "not found" or "failed" is `skipped` with the reason.
  - `extract`: S7 `request_extraction`; `skipped` when there are no ready photos; then waits on the agent run.
  - `compliance`: reuses a scan already in progress, else S11 `request_scan`; waits on it.
  - `index`: S13 `index_listing`.
  - `valuation`: S14 `request_valuation` with a seed fixed per run; waits while the geocode waits, because comps are picked by distance.
- **Idempotent:** a finished step is never run again; a step that started an agent run stores its ID and waits on that run instead of starting another.
- **Retries and budgets:** each step runs inside a savepoint. A refusal (`AppError`) fails the step at once. Any other error is retried on later passes, at most 3 times (`MAX_STEP_ATTEMPTS`). The agent runs keep their own retries. A run has at most 180 passes and a 30-minute deadline; past either it fails and names the steps still waiting.
- **Trace ID:** the request's `X-Request-ID` is stored on the run. `jobs.enqueue` now copies the current request ID into every job's payload as `trace_id`, and `jobs.run_one` sets it as the log context while the job runs. So the request, the workflow passes, the agent jobs, their log lines and their audit events share one ID.
- **Who:** editors of the organisation that owns the listing may start a run (else 403); readers in that organisation may see runs; another organisation gets 404. One active run per listing (409 `workflow_in_progress`). Audited as `workflow.started`.

## Chunks

- [x] **1. Backend.** Models, migration `95a2ca578333`, graph, job, API, trace propagation, tests (`tests/test_workflow.py`, 6).
- [x] **2. Web.** "Workflow" section on the listing page (`ListingWorkflow.tsx`, 2 tests), polls while the run is active.
- [x] **3. Real-stack check and docs.**

## What was built

- API: `POST /api/v1/listings/{id}/workflows` (202), `GET` on the same path (20 newest), `GET /api/v1/workflows/{run_id}` with every step's status, attempts, output (agent run ID, valuation ID, reason) and error.
- Web: "Workflow" section with "Run workflow", the run status, each step with its note, the trace ID and the pass count.

## Acceptance results

- All steps run in order and the run succeeds (`test_run_goes_through_every_step_and_carries_the_trace`).
- The trace ID reaches the workflow, extraction and compliance jobs (same test).
- Extra passes do not start a second extraction or scan (`test_passes_are_idempotent`).
- A broken step is tried 3 times, then fails the run; independent steps still finish (`test_a_broken_step_is_retried_then_fails_the_run`).
- The pass budget stops a run (`test_run_that_outlives_its_budget_fails`).
- One run at a time, editors only, other organisations get 404 (`test_one_run_at_a_time_and_permissions`).
- Real stack (API + worker on the seeded database): a run with demo providers succeeded in 2 passes. A run with the real Gemini key in `.env` hit Gemini HTTP 503 ("high demand"); extraction failed after its own retries, the other steps finished, and the run stopped at its budget.
- All checks pass: API ruff, mypy, alembic check, pytest (307); web lint, typecheck, test (70), build.

## Known limitations

- Waiting steps are polled every 10 s, not woken by the work they wait for.
- When a run fails, steps still waiting stay `waiting`; the agent runs they started carry on and their results stay visible in their own sections.
- A step does not re-run when the listing changes during the run; start a new run.
- A worker started before this sprint does not know `workflow.advance` and fails the job ("No handler registered"). Restart every worker after deploying.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Start, look up or list runs | `workflow.service.start`, `get_run`, `list_runs`, `steps_of` |
| Queue another pass (resume) | `workflow.service.enqueue_pass(session, run)` |
| Statuses | `RUN_STATUSES` includes `awaiting_review` and `cancelled`, reserved for S16 |
| Trace across jobs | automatic: `jobs.enqueue` copies the request ID into `payload["trace_id"]` |

## Next

S16: review gate and monitor (human-review pause and resume, publication gate, cancel and retry, job monitor UI).
