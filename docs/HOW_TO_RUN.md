# How to run and test the app

This guide is for anyone who clones the repository, and for the AI coding assistant they use. It says how to start the app, which accounts to sign in with, how to run the automated checks, and how to test every feature by hand with the result you should see.

Commands are for macOS or Linux. Run them from the repository root unless a step says otherwise. Each step lists what you should see; if you see something else, check [Troubleshooting](#troubleshooting).

## What is built

Sprints 0 to 10 of the plan are done; Sprint 11 (compliance flags) is in progress. Per-sprint notes, with design decisions and known limitations, are in `docs/modules/s<N>-*.md`. The newest one says what is being worked on.

| Area | What a tester can do | Sprint note |
|---|---|---|
| Sign-in, organisations, roles, audit log | Sign in and out, switch organisation, change name and password | `s1-auth-tenancy.md` |
| Members and invitations | Invite by one-time link, change roles, remove members | `s2-invitations-admin.md` |
| Platform administration | Create organisations, issue password reset links, see system status | `s2-invitations-admin.md` |
| Listings | Search, filter, create, edit, move through statuses, share with other organisations | `s3-listings-backend.md`, `s4-listing-ui.md` |
| Photos | Upload, thumbnails made by the worker, remove, retry | `s6-media-jobs.md` |
| AI photo suggestions | Ask the AI what the photos show; accept, edit or reject each suggestion | `s7-ai-extraction.md`, `s8-ai-review.md` |
| Privacy redaction | Blur faces, plates, phone numbers, watermarks and signs in a copy; approve or reject it | `s9-redaction.md` |
| Import | Check and import a CSV of listings; see where an imported listing came from | `s10-import.md` |
| Compliance flags | Check a listing's title and remarks against an illustrative policy (API only so far) | `s11-compliance.md` |

## 1. Prerequisites

- Python 3.15 or newer (`python3 --version`)
- Node.js, current LTS or newer, and pnpm 12 (`corepack enable` gives you pnpm)
- Docker with Compose, running
- Google Chrome, only for the browser end-to-end test
- Free ports: 5432 (Postgres), 8000 (API), 5173 (web)

No API key is needed. Without `GEMINI_API_KEY` the AI features use a demo provider whose output is labelled `[Demo]`, and redaction blurs faces only (see [AI with a real key](#ai-with-a-real-key)).

## 2. First-time setup

```bash
cp .env.example .env
docker compose up -d --wait          # Postgres; should report "Healthy"

cd services/api
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head       # creates the tables
.venv/bin/python -m app.seed         # demo organisations, users, listings and photos
cd ../..

cd apps/web
pnpm install
cd ../..
```

The seed can be run again; it skips what already exists. It refuses to run when `ENVIRONMENT=production`.

## 3. Start the app

Three processes, each in its own terminal, all from the repository root:

```bash
# Terminal 1: API on http://localhost:8000
cd services/api && .venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 2: background job worker (thumbnails, AI runs, redaction, deleting removed files)
cd services/api && .venv/bin/python -m app.worker

# Terminal 3: web app on http://localhost:5173 (proxies /api to port 8000)
cd apps/web && pnpm dev
```

Check that it is up:

```bash
curl -s http://localhost:8000/api/v1/health
```

You should get `{"status":"ok","database":"ok"}`. A 503 `database_unavailable` means Postgres is not reachable.

| What | Where |
|---|---|
| Web app (sign in here) | http://localhost:5173 |
| Interactive API docs (not in production) | http://localhost:8000/api/v1/docs |
| OpenAPI schema | http://localhost:8000/api/v1/openapi.json |

Without the worker the app still works, but photos stay "Processing", and AI and redaction runs stay queued.

## 4. Demo accounts

Every seeded user has the password `local-dev-password`. These accounts exist only in your local database.

| Email | Role | Use it to test |
|---|---|---|
| `platform.admin@demo.example.com` | Platform administrator | Platform page, creating organisations, password reset links |
| `mls.admin@demo.example.com` | MLS administrator, Demo MLS | Members of an MLS organisation |
| `sunrise.admin@demo.example.com` | Brokerage administrator, Sunrise Realty | Approving listings, members, invitations, audit log |
| `sunrise.agent@demo.example.com` | Agent, Sunrise Realty | Creating and editing own listings, photos, AI, import |
| `harbour.admin@demo.example.com` | Brokerage administrator, Harbour Homes | Seeing what another organisation shares |
| `two.orgs@demo.example.com` | Broker at Sunrise Realty, agent at Harbour Homes | Switching organisation |

Seeded listings (all titles start with `[Demo]`; addresses and prices are invented):

| Organisation | Listing | Status | Visibility |
|---|---|---|---|
| Sunrise Realty | 3 BHK apartment near the lake | Active | Network (other organisations see it) |
| Sunrise Realty | Compact studio to let | Draft | Private |
| Sunrise Realty | Garden villa | Pending review | Private |
| Sunrise Realty | Corner office space | Sold | Network |
| Harbour Homes | Sea-facing 2 BHK | Active | Network |

Each seeded listing has two drawn demo photos.

## 5. Automated checks

Postgres must be running. API tests use their own database (`<name>_test`), created automatically, so they never touch your seed data.

```bash
# API: format, lint, types, migrations in sync, tests
cd services/api
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy \
  && .venv/bin/alembic check && .venv/bin/pytest -q
cd ../..

# Web: lint, types, unit tests, production build
cd apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
cd ../..
```

Expected on 2026-11-17: API 233 passed, 2 deselected (the deselected ones are live Gemini tests); web 52 passed. Higher counts later are fine; any failure is not.

Live Gemini tests (need `GEMINI_API_KEY`, use free-tier quota): `cd services/api && .venv/bin/pytest -m live`.

Browser end-to-end test (app running as in step 3, seed loaded, Chrome installed). An agent signs in, creates a listing, finds it, submits it for review and archives it:

```bash
cd apps/web && pnpm e2e
```

CI (`.github/workflows/ci.yml`) runs the same API and web checks on pull requests.

## 6. Manual test walkthrough

Do these in order in http://localhost:5173. Sign out with the button in the header between accounts. Each line is: action, then what you should see.

### 6.1 Sign-in and accounts

1. Sign in with a wrong password. You see an error and stay on the sign-in page.
2. Sign in as `sunrise.agent@demo.example.com`. You see "Working in Sunrise Realty" and nav links including Listings.
3. Open your profile, change your name, save. The header shows the new name.
4. Sign out, sign in as `two.orgs@demo.example.com`. An organisation switcher appears; switch between Sunrise Realty and Harbour Homes. The listings shown change with it.

### 6.2 Members and invitations

1. Sign in as `sunrise.admin@demo.example.com`, open Members.
2. Invite a new email as agent. A one-time invitation link is shown once (no email is sent).
3. Open that link in a private window and accept it, setting a name and password. The page says "You are now a member of Sunrise Realty. Sign in to continue." Sign in with the new account.
4. Back as the admin: the person is listed; change their role, then remove them. Both work and appear in the audit log (`GET /api/v1/audit-events`, see 6.10).
5. Sign in as `sunrise.agent@demo.example.com`: Members shows the list but no invite, role or remove controls.

### 6.3 Platform administration

1. Sign in as `platform.admin@demo.example.com`. The home page shows System status: Operational.
2. Open Platform (nav). The page is headed "Platform administration".
3. Create an organisation. It appears in the list.
4. Issue a password reset link for `sunrise.agent@demo.example.com`. A one-time link is shown; opening it lets you set a new password. Set it back to `local-dev-password`, since the seed does not reset passwords and the end-to-end test uses that one.

### 6.4 Listings

1. As `sunrise.agent@demo.example.com`, open Listings. The four Sunrise listings and the shared Harbour listing appear.
2. Use search and the filters (status, scope, city, price range, sort). The table updates; "Load more" appears when there are more rows.
3. New listing: enter an address, city and listing details, "Create draft listing". The detail page shows it as Draft with "Created as Draft" in the status history.
4. Edit: change the price and the property's bedrooms. Both save. If you edit the same listing in two tabs, the second save reports that someone else changed it and offers a reload.
5. "Submit for review". The status becomes Pending review. As an agent you see no approve button.
6. Sign in as `sunrise.admin@demo.example.com`, open that listing, "Approve and publish". It becomes Active.
7. Archive it (inline confirm). It no longer appears in the listings table.
8. Sharing: sign in as `harbour.admin@demo.example.com`. Sunrise's network listings (lake apartment, corner office) are visible, read-only. Sunrise's private listings (studio, villa) are not. Opening a private listing's URL directly gives "Listing not found".

### 6.5 Photos (worker must be running)

1. As `sunrise.agent@demo.example.com`, open a draft or active listing you are the agent of. The Photos section shows the seeded photos.
2. Upload a JPEG, PNG or WebP. A progress bar shows, then "Processing", then a thumbnail within a few seconds.
3. Upload a `.txt` or a file over 10 MB. It is refused with a message saying what is allowed.
4. Remove a photo. It disappears; its file is deleted after the retention period (7 days by default).

### 6.6 AI photo suggestions

1. On the same listing, AI suggestions, "Analyse photos". The run goes queued, then running, then succeeded.
2. Without a key every suggestion is labelled `[Demo]`; with a key they come from Gemini. Uncertain ones are marked uncertain; each links to the photo it came from.
3. Accept one, edit one (change the value), reject one. Each decision is final. Accepted and edited values appear under Confirmed features.
4. The listing's own fields (bedrooms, area, remarks) do not change. AI never writes them.
5. As `harbour.admin@demo.example.com` on a shared Sunrise listing, you can see suggestions but not decide.

### 6.7 Privacy redaction

1. On a listing photo, "Check for sensitive content". The check runs in the worker.
2. The Privacy redaction section shows the original with found areas outlined next to the blurred copy. The original photo is unchanged.
3. Without a key: faces are blurred (OpenCV, local) and plates, phone numbers, watermarks and signs are listed as "not checked" with the reason. The drawn demo photos contain no faces, so expect no regions; use a photo of yourself to see a face blurred (do not use other people's photos).
4. "Approve copy" or "Reject copy", with an optional note. The decision is final.

### 6.8 Import

1. As `sunrise.agent@demo.example.com`, Listings, "Import listings".
2. "Download a template" gives a CSV with the accepted headers. The field reference lists every field and the column names it accepts.
3. Save this as `portal.csv` and choose it:

   ```csv
   Ref No,Listing Type,Property Type,Title,Price,Address,City,BHK,Carpet Area (sq ft),Pincode
   P-101,Sale,Flat,[Demo] Imported flat,₹1.25 Cr,12 Test Road,Mumbai,3 BHK,1250,400076
   P-102,Lease,Bungalow,[Demo] Imported bungalow,"Rs. 1,50,000",4 Test Lane,Pune,4,2400,411001
   ```

   The preview shows each header with the field it maps to ("BHK (as Bedrooms)"), prices read as 1,25,00,000 and 1,50,000, and an "Import 2 listings" button.
4. Change `Sale` to `Swap` and choose the file again. The row shows "\"Swap\" is not a listing type. Use sale or rent." and there is no Import button.
5. Fix it and import. Each new listing page shows "Imported from portal.csv, row 2" and its original values. Importing the same Ref No again is refused.

### 6.9 Compliance flags (Sprint 11, in progress)

No screen yet (chunk 4 adds it). Test through the API (see 6.10 for signing in with curl; the worker must be running):

1. As `sunrise.agent@demo.example.com`, create a listing whose remarks say `Jain families only. No bachelors.`
2. `POST /api/v1/listings/{id}/compliance/scans` returns 202 with status `queued`.
3. `GET` the same path. Once `succeeded`, `output.findings` lists `IN-HP-01` ("Jain families only") and `IN-HP-04` ("No bachelors"), each with evidence, offsets, severity, confidence, explanation and suggestion. `output.policy_notice` says it is not legal advice.
4. Without `GEMINI_API_KEY`: `is_demo` is true and `output.model_checked` is false with the reason. With a key, Hinglish such as `Sirf shakahari log` should also be found, marked `source: "model"`.
5. Submit a listing for review. A scan starts by itself (audit `compliance.scan_requested` with trigger `submitted`).
6. As `harbour.admin@demo.example.com`, the same path for a shared Sunrise listing returns 404: scans are internal to the owning organisation.

The listing itself never changes. Reviewing findings comes in Sprint 11 chunk 3.

### 6.10 API checks

The interactive docs at http://localhost:8000/api/v1/docs can call every endpoint. Sign in with `POST /api/v1/auth/login` there first; the session cookie is then used for the other calls. From a terminal:

```bash
curl -s -c /tmp/mls.cookies -H 'Content-Type: application/json' \
  -d '{"email":"sunrise.admin@demo.example.com","password":"local-dev-password"}' \
  http://localhost:8000/api/v1/auth/login
curl -s -b /tmp/mls.cookies 'http://localhost:8000/api/v1/listings?limit=5'
curl -s -b /tmp/mls.cookies 'http://localhost:8000/api/v1/audit-events?limit=10'
```

The audit log has no screen yet; read it through `GET /api/v1/audit-events` as an administrator. API conventions (error envelope, `X-Organisation-ID`, `version` for edits, cursor pagination) are in the README.

### 6.11 Phone width

In Chrome DevTools, device toolbar, 375 px wide. The pages do not scroll sideways; wide tables scroll inside their own box; forms are one column.

## AI with a real key

Put `GEMINI_API_KEY=...` in `.env` and restart the API and the worker. Get a key at https://aistudio.google.com/apikey. The free tier may use what you send to improve Google's models, so upload demo photos only. Photos are sent without camera or GPS data. Decisions about the provider are in `docs/decisions/0004-*.md` and `0005-*.md`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| API exits at start with a settings error | `.env` missing or a value malformed. `cp .env.example .env`. |
| `connection refused` on 5432 | Postgres not running: `docker compose up -d --wait`. Another Postgres on 5432: set `POSTGRES_PORT` and the port in `DATABASE_URL` in `.env`. |
| Photos stay "Processing", AI runs stay queued | The worker (terminal 2) is not running. |
| Photos stop loading after an API restart | Download links are signed with a per-process key in development. Reload the page. |
| Sign-in works but lists are empty | Seed not loaded: `cd services/api && .venv/bin/python -m app.seed`. |
| Web type errors after pulling API changes | `cd apps/web && pnpm gen:api` (API code must be importable; Postgres running). |
| `alembic check` reports changes | A model changed without a migration. `alembic revision --autogenerate -m "..."`, review it, `alembic upgrade head`. |

## Running the production image locally

The deployable image serves the API and the built web app on one port. Steps are in `docs/deployment/render.md` ("Running the same image locally").

## Notes for AI assistants working on this repository

- Start here, then read the newest `docs/modules/s<N>-*.md`. Its status line, chunk checklist and "Next" section say what is done and what is next. Each finished sprint's "Shared pieces later sprints must reuse" table lists the code to reuse.
- To verify the app: run section 5, then walk section 6 in a browser. Report each step as passed or failed with what you saw. Do not report a step as passed without running it.
- Use only the seeded `[Demo]` data and demo photos. Do not upload real people's photos or real listings, and do not send them to Gemini.
- The API is the source of truth for permissions. The web app hides controls by `my_permissions`, `can_edit` and `allowed_transitions`, never by role name.
- AI output is a suggestion. It never writes agent-entered listing fields; a person decides. Compliance results are decision support under an illustrative policy, never a statement that a listing is legally compliant.
- After changing the API, run `pnpm gen:api` in `apps/web`. After changing a model, add an Alembic migration.
