# Sprint 11: Compliance flags and review queue (Module 6b)

**Status: done (2026-11-17).** All five chunks are finished. Staged, not committed.

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s11-compliance` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan and INSTRUCTIONS.md §2.2 and Module 6, second half): a policy model with version and jurisdiction; an illustrative India policy pack; a rule check plus a Gemini check of listing remarks; findings with evidence, severity, confidence, policy reference and a suggested alternative; a reviewer queue with accept, dismiss and request edits; an appeal trail; everything audited. The UI never says a listing is "legally compliant" because a check found nothing.

## Design decisions (reversible; made 2026-11-17)

- **The policy is a house policy, not law.** India has no single equivalent of US Fair Housing or Clear Cooperation rules, and INSTRUCTIONS.md §14 question 4 is unanswered. The pack `in-house-illustrative` is written as an example organisation policy for the demo. It cites its own rule IDs only, never statutes, and every screen that shows a result says it is not a legal review. US rules are not applied.
- **Policy model** (`app/modules/compliance/policy.py`): `Policy` (id, version, jurisdiction, name, notice, rules) and `Rule` (id, category, severity, confidence, title, explanation, suggestion, patterns). Kept in code, not a table: a change to a rule is a code change with a version bump and a test. Per-organisation policies are out of scope.
- **Rules in the India pack** (version `2026.11-1`, jurisdiction `IN`): who may live or buy by religion, caste or community (`IN-HP-01`, high); by region, language or nationality (`IN-HP-02`, high); by food habits (`IN-HP-03`, medium); by marital or family status (`IN-HP-04`, medium); by gender (`IN-HP-05`, low, since a PG or shared room may legitimately be single-gender); guaranteed or assured returns (`IN-HP-06`, medium).
- **Patterns need an exclusion word** ("only", "no ...s", "not allowed"). A remark that merely mentions a community, a temple or a vegetarian restaurant is not flagged. Matching is case-insensitive; overlapping matches of one rule are merged.
- **Confidence** is set per rule: how likely a match is to be a real problem. A person decides every finding; nothing is rejected, hidden or rewritten automatically (§2.2 safeguards).
- **Scans** (chunk 2, `app/modules/compliance/service.py`): an `AgentRun` with `agent="compliance"`. Its inputs hold the listing version, the trigger (`manual` or `submitted`), the policy id and version, and a copy of the title and remarks as they were when asked, so offsets point into what was checked. Output is `ComplianceScan`: the policy (id, version, name, notice, jurisdiction) copied in, and findings marked `source: "rule"` or `"model"`.
- **Title and remarks are both checked.** Each finding names its `field`.
- **The rule check always runs.** The Gemini check (`GeminiTextReviewer`) looks for indirect wording and Hindi, Marathi or Hinglish text. Without a key, or when Gemini still fails after 3 tries (a refusal is not retried), the scan finishes with the rules only and `model_checked: false` plus the reason. The demo reviewer reports nothing; no invented findings.
- **Model findings are checked before use.** The quote must occur in the field (exact, then ignoring case) and the rule ID must be in the policy; otherwise the finding is dropped and counted in `model_dropped`. One a rule already reported at the same place is skipped. Severity comes from the policy, confidence from the model.
- **Scans are internal.** Only the organisation that owns the listing sees them (another organisation gets 404, even for a shared listing). Editors request; readers in the owning organisation list.
- **Submitting for review starts a scan** (in `listings/router.py`), skipped when one is already queued or running. One scan at a time per listing (`409 scan_in_progress`). A scan queued under an older policy version fails and asks to be run again.
- **Review** (chunk 3): a scan with findings gets one `ReviewTask` (`subject_type="compliance_scan"`). Item keys per finding index `i`: `"i"` (the decision), `"i:appeal"`, `"i:appeal_decision"`. The unique key per item makes every step happen once. `DECISIONS` gained `dismissed`, `edits_requested`, `appealed`, `upheld`, `overturned` (migration `3c5d2e7f9a10`).
- **Decisions**: `accepted` (a real problem; the agent should edit), `dismissed` (not a problem), `edits_requested` (a note is required). Final; a mistake is corrected through the appeal.
- **Who reviews**: holders of `listing:publish` in the owning organisation (MLS admin, brokerage admin, broker), never on a listing where they are the listing agent. An appeal ruling must come from someone other than the first reviewer (`403 same_reviewer`).
- **Appeal**: only the listing agent, once per finding, only against `accepted` or `edits_requested`, with a reason. The ruling (`upheld` or `overturned`) needs a reason too.
- **A newer scan replaces older ones**: when it finishes, the older scans' reviews close (`409 scan_superseded` on any later decision there), unfinished appeals included. The queue only shows open reviews. A scan that finishes late after retries, when a newer one has already finished, gets no review.
- **Queue** (`GET /api/v1/compliance/queue`): undecided findings and appeals without a ruling, oldest first, in the active organisation, without archived listings or listings where the caller is the agent. Decisions are made on the listing page, where the full text is.
- **A scan whose job failed outside its handler** (a worker on older code took it) is shown as failed with the job's error and does not block a new check.

## How to resume

1. `git status` and `git log --oneline | head -3` to see what is committed and what is staged.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Find the first unchecked chunk below. Do only that chunk.
4. Run the checks listed under "Checks", tick the chunk, add a line under "Log", update `docs/HOW_TO_RUN.md` if the chunk adds something a tester can see, stage, stop.

## Chunks

- [x] **1. Policy pack and rule check.** `app/modules/compliance/policy.py`: `Policy`, `Rule`, `Finding`, `INDIA_POLICY`, `check_remarks(text, policy)`. No database, no API. `tests/test_compliance_rules.py`: a test set of flagged and clean remarks, evidence offsets, pack sanity.
- [x] **2. Scans.** `agent="compliance"` runs: job handler that runs `check_remarks` then the Gemini check (`compliance/providers.py`; the demo reviewer reports nothing and the scan says the model did not check), output schema in `compliance/schemas.py`. `POST /api/v1/listings/{id}/compliance/scans` (202, editors), `GET` same path (readers; another organisation 404). Scan on submit for review too. Audit `compliance.scan_requested`. Tests with a fake provider. `pnpm gen:api`.
- [x] **3. Review and appeal.** Migration widening `DECISIONS`. `POST /api/v1/compliance/scans/{id}/findings/{i}/decision` (accept, dismiss, request edits; `listing:publish`), `POST .../findings/{i}/appeal` (listing agent, once per finding, reason required), `POST .../findings/{i}/appeal/decision` (uphold or overturn). `GET /api/v1/compliance/queue` (open findings in the organisation, oldest first). Audit every step. Tests.
- [x] **4. Web.** Listing page section "Policy check": run a check, findings with the phrase highlighted in the remarks, severity, confidence, rule, explanation, suggestion; decision and appeal controls by permission. Page `#/compliance` ("Review queue" in the nav for `listing:publish`): the queue. Wording: "No findings under <policy> <version>. This is not a legal review." Tests.
- [x] **5. Seed, browser check, docs.** One seeded `[Demo]` listing with flagged remarks. Chrome check at desktop and 375 px. Fill in the sections below, README status, `docs/security/rbac-matrix.md`, `docs/HOW_TO_RUN.md`. Run every check.

## Conventions to follow (already in the codebase)

- Runs and jobs: `docs/modules/s7-ai-extraction.md` and `s9-redaction.md` "Shared pieces". Gemini structured output: subclass `GeminiClient`, `_generate` then `_parse`.
- Reviews: `review.service.open_task`, `decide`, `decisions_for`, `close` (`docs/modules/s8-ai-review.md`).
- Remarks are agent-typed fields: AI never writes them. A suggestion is shown, the agent edits.
- Errors use `AppError`; permissions use `require(...)` and `listings.service.can_edit`, never role names.
- Web: `api()`, `useAction()`, `useList()` in `apps/web/src/api.ts`; poll like `ListingSuggestions.tsx`.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/alembic check && .venv/bin/pytest -q
# from apps/web (only if the web app or API schema changed)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk: date, what was done, anything left open)

- 2026-11-17, chunk 1 done. `app/modules/compliance/policy.py` with the six-rule India pack and `check_remarks`; `tests/test_compliance_rules.py`. Not wired to the API yet, so nothing is visible in the app. Also added `docs/HOW_TO_RUN.md` (run and test guide for people and AI assistants) and root `AGENTS.md` / `CLAUDE.md` pointing to it.

- 2026-11-17, chunk 2 done. `compliance/schemas.py`, `providers.py` (demo and Gemini reviewers), `service.py` (request, list, job `compliance.scan`), `router.py`; scan on submit in `listings/router.py`; audit `compliance.scan_requested` with trigger and policy version. `tests/test_compliance_scans.py` (8 tests) and a live test in `tests/test_ai_live.py`. `pnpm gen:api` run. API 233 passed; web 52 passed, lint, typecheck, build. Open: the live Gemini test did not run to the end (HTTP 503, then the free-tier quota was used up), so the prompt and schema are untested against real Gemini; run `pytest -m live -k listing_text` when quota resets.

- 2026-11-17, chunk 3 done. Migration widening review decisions; `decide_finding`, `appeal`, `decide_appeal`, `queue`, `_supersede` in `compliance/service.py`; routes in `compliance/router.py`; scan output gains `reviews`, `review_open`, `can_review`, `can_appeal`, `checked_title`, `checked_remarks`. Schemas named `Compliance*Out` (the generated web types clashed with the AI module's `DecisionOut`). `tests/test_compliance_review.py` (7 tests).
- 2026-11-17, chunk 4 done. `ListingCompliance.tsx` (section on the listing page, owning organisation only), `ComplianceQueue.tsx` (`#/compliance`), nav link and route in `Workspace.tsx`, CSS. `ListingCompliance.test.tsx` (7 tests).
- 2026-11-17, chunk 5 done. Seed: `[Demo] 2 BHK to let near the IT park` (Sunrise, pending review, flagged remarks, check queued); added on its own so existing databases get it. Browser check in Chrome (below). Fixes from it: "Request edits" stays disabled until a note is typed; no double full stop after a note; the full review trail is listed under an appealed finding; a scan stalled by an old worker shows as failed. Docs: README, RBAC matrix, HOW_TO_RUN 6.9.

## What was built

- **Policy pack** (`compliance/policy.py`): six illustrative India house rules with id, category, severity, confidence, explanation and suggestion; `check_remarks` with exact evidence offsets.
- **Scans**: rule check plus a Gemini check of title and remarks, as a background job; on request or on submit for review; audited; internal to the owning organisation.
- **Review and appeal**: accept, dismiss, request edits; one appeal by the listing agent; a ruling by a second reviewer; every step audited with the rule and policy version.
- **Web**: "Policy check" on the listing page (phrase marked in its sentence, severity, rule, source, confidence, explanation, suggestion, review state and trail, controls by permission); "Review queue" page.
- **Seed** listing with flagged remarks.

| Endpoint | Who |
|---|---|
| `POST /api/v1/listings/{id}/compliance/scans` (202) | editors of the listing |
| `GET /api/v1/listings/{id}/compliance/scans` | readers in the owning organisation |
| `POST /api/v1/compliance/scans/{id}/findings/{i}/decision` (201) | `listing:publish`, not the listing agent |
| `POST /api/v1/compliance/scans/{id}/findings/{i}/appeal` (201) | the listing agent |
| `POST /api/v1/compliance/scans/{id}/findings/{i}/appeal/decision` (201) | `listing:publish`, not the agent, not the first reviewer |
| `GET /api/v1/compliance/queue` | `listing:publish` |

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Check listing text before it leaves the organisation (Sprint 17 syndication, public pages) | The newest scan from `compliance.service.list_scans`; its findings' review states. Decide in that sprint whether open or confirmed findings block publishing; nothing blocks today. |
| Start a check from another flow (import, workflow in Sprint 15) | `compliance.service.scan_on_submit(session, ctx, listing_id)` (skips if one is running), then `record_requested(...)` for the audit. |
| A new rule or a changed pattern | Edit `INDIA_POLICY` in `policy.py`, bump `version`, add cases to `tests/test_compliance_rules.py`. Queued scans under the old version fail and ask to be run again. |
| Another policy (jurisdiction or organisation) | A second `Policy` and a choice in `compliance.service.get_policy()`; scans already store the policy id and version. |
| A person reviews items with an appeal trail (Sprint 16 workflows) | The `i`, `i:appeal`, `i:appeal_decision` item keys on `review.service`, and `FindingReview` / `reviews()` in `compliance/service.py`. |
| Tests that touch the model check | Monkeypatch `app.modules.compliance.service.get_reviewer` with a fake (`FakeReviewer` in `tests/test_compliance_scans.py`). |

## Acceptance results

- A test set of remarks produces explainable flags: yes. 15 flagged and 9 clean remarks in `tests/test_compliance_rules.py`; each flag has evidence, offsets, rule, severity, confidence, explanation and suggestion. In Chrome the seeded listing showed "Vegetarians only" (IN-HP-03) and "no bachelors" (IN-HP-04) marked in their sentence.
- Reviewer can accept, dismiss or request edits: yes (API tests; in Chrome as `sunrise.admin`: "Confirm issue" on one finding, "Request edits" with a note on the other).
- Override and appeal: in Chrome the agent appealed; the first reviewer's ruling was refused (`same_reviewer`); `two.orgs` (broker at Sunrise) overturned it; the listing shows the trail decision, appeal, ruling with names and times.
- Policy version and reviewer action are auditable: yes. `compliance.scan_requested`, `compliance.finding_decided`, `compliance.finding_appealed`, `compliance.appeal_decided`, each with rule id, policy id and version 2026.11-1 (seen through `GET /api/v1/audit-events`).
- The UI does not call a listing legally compliant: every result shows the policy notice ("not legal advice"); no findings reads "No findings under ... This is not a legal review." A test checks the word "compliant" does not appear.
- Nothing is rejected, hidden or rewritten automatically: the listing's text is unchanged after decisions (API test).
- Another organisation: `harbour.admin` gets 200 on a shared Sunrise listing and 404 on its scans; the queue is per organisation.
- Gemini: with the free-tier quota used up, the check finished after retries with the rules only and said why. The live test of the Gemini prompt (`pytest -m live -k listing_text`) has not passed yet: HTTP 503, then quota exhausted.
- Narrow layout: the window could not go below 606 px; with the app set to 375 px wide, nothing in the section overflows.
- Checks: ruff, format, mypy, `alembic check`, pytest (241 passed); web lint, typecheck, test (59 passed, 3 runs), build; end-to-end test passed; Docker build.

## Known limitations

- The policy is illustrative, written for the demo, not reviewed by a lawyer, and not Indian law (INSTRUCTIONS.md §14 question 4 is open). Clear Cooperation monitoring is not built: no applicable rules or lawful data source are confirmed.
- The rules match English only. Hindi, Marathi and Hinglish wording ("sirf", "keval") needs the Gemini check, which is unverified against the live API so far.
- Patterns are lists of words. A community or phrase not in the list is missed by the rule check.
- Findings do not block anything: a listing with confirmed findings can still be approved. Whether they should is a product decision.
- A newer scan closes the older review even if an appeal there was waiting; the appeal has to be made again on the new scan.
- The queue is not paginated (it loads every open review of the organisation).
- A worker running older code can still take a new job and fail it ("No handler registered"); the scan then shows as failed. Restart every worker after pulling.
- Policies are in code, one for all organisations; no per-organisation configuration screen.

## Next

Phase B continues with Sprint 12 (geospatial) or Sprint 13 (semantic search); Sprint 14 needs 13. The plan's shortest path to a full demo goes to Sprint 13, then 15 and 16.
