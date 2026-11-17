# Handover checklist

For moving the project to the evaluating company (WildCatter) and giving reviewers access. Tick each item when done. Nothing here is pushed or transferred until the developer has permission and repository access from the company.

## 1. Code is ready

- [ ] All checks pass locally ([HOW_TO_RUN.md](HOW_TO_RUN.md) section 5): API (ruff, mypy, `alembic check`, pytest), web (lint, typecheck, tests, build), Playwright journeys.
- [ ] Every change is committed; `git status` is clean. Untracked iCloud copies named `* 2.*` must not be committed (153 of them were moved to `../ai-native-mls-duplicates-2026-11-17/` on 2026-11-17).
- [ ] Pushed to the developer's GitHub repository and merged into `main` through a pull request with green CI (`api`, `web`, `e2e`, `audit`).

## 2. No secrets or private data

- [ ] No keys, passwords or tokens in tracked files. Check:

  ```bash
  git ls-files | xargs grep -nE "AIza[0-9A-Za-z_-]{30}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20}|BEGIN (RSA |EC )?PRIVATE" ; echo "exit $?"
  ```

  `exit 1` with no lines means nothing was found (checked on 2026-11-17).
- [ ] `.env` is not tracked (`git ls-files .env` prints nothing).
- [ ] The Gemini development key that was shared in a chat during Sprint 7 is **rotated** (Google AI Studio > API keys > delete it, create a new one) before any public demo.
- [ ] Demo data is fictional and marked `[Demo]`; no real people's photos were uploaded to the demo.

## 3. Live demo

- [ ] Deployed on Vercel following [deployment/vercel.md](deployment/vercel.md): Neon database, R2 bucket, environment variables, job runner every minute.
- [ ] `GET /api/v1/health` answers `{"status":"ok","database":"ok"}`.
- [ ] The demo script ([DEMO.md](DEMO.md)) walked through on the live URL, on a desktop and on a phone.
- [ ] Playwright against the live URL: `E2E_BASE_URL=<url> E2E_PASSWORD=<SEED_PASSWORD> pnpm e2e` from `apps/web`.
- [ ] Recovery from a failed background task: a job failed on purpose (for example, the job runner stopped while a photo uploads, or a webhook to a closed port) is listed on Monitor or Platform > Service health and recovers with "Retry job" or "Send again".
- [ ] Logs visible in Vercel (Project > Logs); the API logs one JSON line per request with its request ID.
- [ ] The live URL is in the README's "Live demo" line.
- [ ] The demo password (`SEED_PASSWORD`) is sent to reviewers privately, never in the repository or an issue.

## 4. Release

- [ ] Tag the release on `main` after the merge (the developer runs this; Claude does not tag or push):

  ```bash
  git checkout main && git pull
  git tag -a v1.0.0 -m "AI-Native MLS 1.0.0: demo-ready handover"
  git push origin v1.0.0
  ```

- [ ] Optional: a GitHub release from that tag, with a link to the demo, [DEMO.md](DEMO.md) and [known-limitations.md](known-limitations.md).

## 5. Transfer to the company

Only after the company grants permission and repository access:

- [ ] Agree on transfer or fork. A **transfer** (GitHub > Settings > Danger Zone > Transfer ownership) moves issues, pull requests and stars and redirects the old URL; it needs the developer to be allowed to create repositories in the company's organisation. A **fork or mirror** keeps the original under the developer's account.
- [ ] Before transferring: remove deployment secrets from the repository's GitHub settings (Actions secrets) that belong to the developer's accounts; the new owner sets their own.
- [ ] After transferring: the Vercel project's Git connection points at the old repository. Either the company imports the repository into its own Vercel team (and creates its own Neon database, R2 bucket and secrets), or the developer reconnects the existing project (Project > Settings > Git).
- [ ] Hand over, privately: the live URL, the demo password, who owns the Vercel, Neon, Cloudflare and Google accounts, and when they will be shut down or handed over.
- [ ] Point the company's reviewers at the README (setup, architecture, features, limitations, demo accounts), [DEMO.md](DEMO.md), [architecture.md](architecture.md) and [known-limitations.md](known-limitations.md).

## Where things are

| Need | File |
|---|---|
| Run, test, every feature by hand | [HOW_TO_RUN.md](HOW_TO_RUN.md) |
| Guided demo with accounts | [DEMO.md](DEMO.md) |
| System, workflow and data diagrams | [architecture.md](architecture.md) |
| Limits and roadmap | [known-limitations.md](known-limitations.md) |
| Deploy | [deployment/vercel.md](deployment/vercel.md) (Render: [deployment/render.md](deployment/render.md)) |
| Operate (monitoring, incidents, restore, retention) | [operations/runbooks.md](operations/runbooks.md) |
| API for other systems | [api/developer-guide.md](api/developer-guide.md) |
| Permissions per role | [security/rbac-matrix.md](security/rbac-matrix.md) |
| Why things are built this way | [decisions/](decisions/) |
| What each sprint built | [modules/](modules/) |
