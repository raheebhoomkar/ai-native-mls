# Sprint 11: Compliance flags and review queue (Module 6b)

**Status: in progress.** Chunk 1 of 5 is done. Staged, not committed.

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s11-compliance` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan and INSTRUCTIONS.md §2.2 and Module 6, second half): a policy model with version and jurisdiction; an illustrative India policy pack; a rule check plus a Gemini check of listing remarks; findings with evidence, severity, confidence, policy reference and a suggested alternative; a reviewer queue with accept, dismiss and request edits; an appeal trail; everything audited. The UI never says a listing is "legally compliant" because a check found nothing.

## Design decisions (reversible; made 2026-11-17)

- **The policy is a house policy, not law.** India has no single equivalent of US Fair Housing or Clear Cooperation rules, and INSTRUCTIONS.md §14 question 4 is unanswered. The pack `in-house-illustrative` is written as an example organisation policy for the demo. It cites its own rule IDs only, never statutes, and every screen that shows a result says it is not a legal review. US rules are not applied.
- **Policy model** (`app/modules/compliance/policy.py`): `Policy` (id, version, jurisdiction, name, notice, rules) and `Rule` (id, category, severity, confidence, title, explanation, suggestion, patterns). Kept in code, not a table: a change to a rule is a code change with a version bump and a test. Per-organisation policies are out of scope.
- **Rules in the India pack** (version `2026.11-1`, jurisdiction `IN`): who may live or buy by religion, caste or community (`IN-HP-01`, high); by region, language or nationality (`IN-HP-02`, high); by food habits (`IN-HP-03`, medium); by marital or family status (`IN-HP-04`, medium); by gender (`IN-HP-05`, low, since a PG or shared room may legitimately be single-gender); guaranteed or assured returns (`IN-HP-06`, medium).
- **Patterns need an exclusion word** ("only", "no ...s", "not allowed"). A remark that merely mentions a community, a temple or a vegetarian restaurant is not flagged. Matching is case-insensitive; overlapping matches of one rule are merged.
- **Confidence** is set per rule: how likely a match is to be a real problem. A person decides every finding; nothing is rejected, hidden or rewritten automatically (§2.2 safeguards).
- **Planned for chunk 2**: a scan is an `AgentRun` with `agent="compliance"`, the policy id and version in its inputs, and findings in `output`, each marked `source: "rule"` or `"model"`. The rule check always runs; the Gemini check finds what patterns miss (indirect wording) and is "not checked" with a reason when there is no key or it fails, as in Sprint 9.
- **Planned for chunk 3**: decisions on a finding are `accepted` (a real problem: the agent must edit), `dismissed` (not a problem), `edits_requested` (reviewer wants a rewrite, with a note). The listing agent may appeal an accepted or edits-requested finding once, with a reason; a reviewer then upholds or overturns it. All of it uses `review.service` (widen `DECISIONS` in a migration) and is audited. Who reviews: `listing:publish` holders (MLS admin, brokerage admin, broker), so an agent never reviews their own listing.

## How to resume

1. `git status` and `git log --oneline | head -3` to see what is committed and what is staged.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Find the first unchecked chunk below. Do only that chunk.
4. Run the checks listed under "Checks", tick the chunk, add a line under "Log", update `docs/HOW_TO_RUN.md` if the chunk adds something a tester can see, stage, stop.

## Chunks

- [x] **1. Policy pack and rule check.** `app/modules/compliance/policy.py`: `Policy`, `Rule`, `Finding`, `INDIA_POLICY`, `check_remarks(text, policy)`. No database, no API. `tests/test_compliance_rules.py`: a test set of flagged and clean remarks, evidence offsets, pack sanity.
- [ ] **2. Scans.** `agent="compliance"` runs: job handler that runs `check_remarks` then the Gemini check (new provider method, demo adapter labelled `[Demo]`), output schema in `ai/schemas.py`. `POST /api/v1/listings/{id}/compliance/scans` (202, editors), `GET` same path (readers; another organisation 404). Scan on submit for review too. Audit `compliance.scan_requested`. Tests with a fake provider. `pnpm gen:api`.
- [ ] **3. Review and appeal.** Migration widening `DECISIONS`. `POST /api/v1/compliance/scans/{id}/decisions` (accept, dismiss, request edits; `listing:publish`), `POST .../appeals` (listing agent, once per finding, reason required), appeal decision (uphold or overturn). `GET /api/v1/compliance/queue` (open findings in the organisation, oldest first). Audit every step. Tests.
- [ ] **4. Web.** Listing page section "Policy check": run a check, findings with the phrase highlighted in the remarks, severity, confidence, rule, explanation, suggestion; decision and appeal controls by permission. Page `/compliance` (nav for `listing:publish`): the queue. Wording: "No findings under <policy> <version>. This is not a legal review." Tests.
- [ ] **5. Seed, browser check, docs.** One seeded `[Demo]` listing with flagged remarks. Chrome check at desktop and 375 px. Fill in the sections below, README status, `docs/security/rbac-matrix.md`, `docs/HOW_TO_RUN.md`. Run every check.

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

## What was built

(filled in at the end of the sprint)

## Shared pieces later sprints must reuse

(filled in at the end of the sprint)

## Acceptance results

(filled in at the end of the sprint)

## Known limitations

- English only. Hindi, Marathi and Hinglish wording ("sirf", "keval") is not matched by the rules; the Gemini check (chunk 2) may catch some of it.
- Patterns are lists of words. A community or phrase not in the list is missed by the rule check.

## Next

Chunk 2.
