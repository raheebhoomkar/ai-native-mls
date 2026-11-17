# How to run and test the app

This guide is for anyone who clones the repository, and for the AI coding assistant they use. It says how to start the app, which accounts to sign in with, how to run the automated checks, and how to test every feature by hand with the result you should see.

Commands are for macOS or Linux. Run them from the repository root unless a step says otherwise. Each step lists what you should see; if you see something else, check [Troubleshooting](#troubleshooting).

## What is built

Sprints 0 to 16 of the plan are done (Phases A and B, and S15–S16 of Phase C). Per-sprint notes, with design decisions and known limitations, are in `docs/modules/s<N>-*.md`. The newest one says what is being worked on.

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
| Compliance flags | Check titles and remarks against an illustrative India policy; review queue; accept, dismiss, request edits; appeal | `s11-compliance.md` |
| Maps and location | See where a property is and how exact the point is; set it by hand; show listings on a map and search the visible area | `s12-geospatial.md` |
| Semantic search | Describe the home in your own words; listings are ranked by match, with the reason shown | `s13-semantic-search.md` |
| Valuation | Estimate a range from comparable reported sales, with comps, assumptions and a days-on-market simulation | `s14-valuation.md` |
| Workflow | Run every step on a listing at once (locate, read photos, policy check, human review, search index, valuation); it pauses for review, blocks approval until done; cancel, retry; Monitor page | `s15-workflow-core.md`, `s16-review-gate-monitor.md` |

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

Expected on 2026-11-17: API 241 passed, 3 deselected (the deselected ones are live Gemini tests); web 59 passed. Higher counts later are fine; any failure is not.

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
4. Back as the admin: the person is listed; change their role, then remove them. Both work and appear in the audit log (`GET /api/v1/audit-events`, see 6.11).
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

### 6.9 Policy checks (compliance flags)

The worker must be running. The seed adds `[Demo] 2 BHK to let near the IT park` (Sunrise Realty, pending review) whose remarks say "Vegetarians only, no bachelors.", with a check already queued.

1. As `sunrise.agent@demo.example.com`, open that listing. The "Policy check" section (below the photos) shows two findings: "Vegetarians only" (rule IN-HP-03, food habits) and "no bachelors" (IN-HP-04, marital status). Each shows the phrase marked in its sentence, severity, rule, "word rule", confidence, explanation and a suggestion, and "Waiting for review". The agent sees no decision buttons.
2. Without `GEMINI_API_KEY` a note says only the word rules ran, with a "Demo" badge. With a key, the AI check also runs; when Gemini fails (or the free quota is used up) the check still finishes after about 90 seconds of retries, with a note saying the AI check did not run and why.
3. The section says it is not a legal review. With no findings it says "No findings under ... This is not a legal review." It never says "compliant".
4. Sign in as `sunrise.admin@demo.example.com`. "Review queue" in the nav lists both findings, oldest first, each linked to the listing.
5. On the listing, finding 1: "Confirm issue". Finding 2: "Request edits" stays disabled until a note is typed; then it is recorded. Both leave the queue.
6. As the agent: under finding 1, enter a reason and "Appeal". The line says "Appealed by ... Waiting for another reviewer." It appears in the queue again as appealed.
7. As `sunrise.admin@demo.example.com` (who made the first decision): "Uphold decision" or "Overturn decision" gives "Another reviewer must decide this appeal."
8. As `two.orgs@demo.example.com` working in Sunrise Realty (a broker): rule on the appeal with a reason. The finding shows the result and, below it, the full trail: decision, appeal, ruling, each with name and time.
9. As the agent, edit the remarks. The section says the listing changed after the check; "Check again" runs a new check, and the older check's review closes ("A newer check replaced this one").
10. Submitting any listing for review starts a check by itself.
11. As `harbour.admin@demo.example.com`, open a shared Sunrise listing: there is no Policy check section, and `GET /api/v1/listings/{id}/compliance/scans` returns 404.
12. Audit log (`GET /api/v1/audit-events`): `compliance.scan_requested`, `compliance.finding_decided`, `compliance.finding_appealed`, `compliance.appeal_decided`, each with the rule and policy version.
13. Approving a listing (pending review to active) while a finding of its newest finished check is open, confirmed, under appeal or upheld fails with "The policy check has N finding(s) still open or confirmed..." (`409 compliance_findings_open`). Dismiss the findings, or overturn them on appeal, and approval works.

The listing's text never changes because of a check or a decision; the agent edits it.

### 6.10 Maps and location (worker must be running)

New and changed addresses are located by a background job. Without settings, the labelled demo geocoder is used: it knows the centres of a few Indian cities and of the seeded localities (Powai, Andheri West, Worli, Koregaon Park, Baner), and nothing more precise. `GEOCODER=nominatim` uses OpenStreetMap Nominatim instead (1 request per second; set `GEOCODER_USER_AGENT` with a contact). Map tiles come from OpenStreetMap's public tile server, which allows light use only.

1. As `sunrise.agent@demo.example.com`, open `[Demo] 3 BHK apartment near the lake`. The "Location" section shows the coordinates, "Accurate to the area", "Source: demo geocoder (approximate centres of known areas and cities)" and the date, with a map marker in Powai. The map credits "© OpenStreetMap contributors".
2. "Set the point by hand": click the map (the coordinates fill in) or type them, then "Save point". The text now says "Accurate to the building. Source: set by hand". Change the address: the point set by hand stays.
3. Create a property in a city the demo does not know (for example "Atlantis"): the listing shows "Finding this address on the map…", then "No match for this address. Set the point by hand." Change the city to Pune: it is located again.
4. "Neighbourhood" lists nearest metro station, schools within 2 km and flood risk as "Not available: No neighbourhood data source is set up." No value is invented.
5. Listings page: "Show map" shows the listings of the current page as markers (click one to open it) and says how many have no location. Zoom to Mumbai and press "Search this area": only listings inside the map area are listed, with "Any area" to undo. "Clear filters" also removes it.
6. As `harbour.admin@demo.example.com`, a shared Sunrise listing shows its point and map but no "Set the point by hand" and no "Neighbourhood".
7. API: `GET /api/v1/listings?near_lat=19.076&near_lon=72.8777&radius_km=10` lists listings within 10 km with `distance_km`; `min_lat`, `min_lon`, `max_lat`, `max_lon` give a box. `PUT /api/v1/properties/{id}/location` sets a point; audit actions `property.geocoded` and `property.location_set`.

### 6.11 Semantic search (worker must be running)

Every listing change writes an outbox event, and the worker re-indexes the listing. Without settings, the labelled demo embedder is used: it matches shared words and spellings, not meaning. `EMBEDDER=gemini` (with `GEMINI_API_KEY`) uses Gemini embeddings; see [AI with a real key](#ai-with-a-real-key). Vectors are kept in Postgres unless `VECTOR_STORE=qdrant`.

1. As `sunrise.agent@demo.example.com`, Listings page, type `apartment near the lake` in "Describe the home" and press Search. "[Demo] 3 BHK apartment near the lake" comes first. Above the table: "Best matches first. Demo embedder: it matches shared words and spellings, not meaning." The last column, "Why it matched", shows the score, the shared words and any filters used.
2. Add a filter (for example City `Pune`) and search again: only Pune listings are ranked, and "filters: city" appears.
3. Edit a listing's title to include `rooftop terrace`, wait a few seconds, describe `rooftop terrace`: it comes first. Withdraw it: it no longer appears.
4. As `harbour.admin@demo.example.com`, describe `apartment near the lake`: Harbour's own listings and Sunrise's shared active listings appear; Sunrise drafts and private listings never do.
5. Clear "Describe the home" and press Search: the normal list and sort come back.
6. API: `GET /api/v1/listings/search?q=sea%20facing&city=Mumbai` returns `items` of `{listing, score, explanation}`. If the embedder is down: 503 `search_unavailable`.

### 6.12 Valuation

Estimates use sold listings the caller may see whose sale price the listing agent reported. The seed adds six `[Demo] Sold:` apartments in Powai with invented prices and dates. This is decision support, not an appraisal.

1. As `sunrise.agent@demo.example.com`, open `[Demo] 3 BHK apartment near the lake`. The "Valuation" section starts with "Not an appraisal and not a guaranteed sale price…". Press "Estimate value".
2. You see "Estimated range ₹… to ₹…, middle ₹…. From 6 reported sales closed between … and …, by price per sq ft times 1250 sq ft." Below: "Days on market" with simulated percentiles and the share sold within 30, 60 and 90 days ("A scenario, not a forecast"), "Offers are not recorded…", and a comparable sales table whose caption says the prices are reported by agents and not verified.
3. Open "Assumptions": the comp rules, "Condition is not recorded, so it is not used", the model and simulation versions and the seed.
4. Open `[Demo] Garden villa` (Pune, no sold villas) and press "Estimate value": "Insufficient data: 0 comparable sales found, at least 3 needed. No estimate is shown." No number appears.
5. As `harbour.admin@demo.example.com`, open the shared lake listing: there is no "Valuation" section. `POST /api/v1/listings/{id}/valuations` answers 404.
6. Reproducibility: `POST /api/v1/listings/{id}/valuations` with `{"seed": 42}` twice gives the same `result.simulation`.
7. Outcome: value a listing, then mark it sold with a price; with the worker running, the valuation shows "Sold for … The estimate's middle was …% above/below it, inside/outside the range." `GET /api/v1/valuations/evaluation` reports the count, median absolute error and share inside the range per model version.

### 6.12a Workflow (worker must be running)

1. Sign in as `sunrise.agent@demo.example.com` and open one of your listings.
2. In "Workflow", click "Run workflow". The button changes to "Workflow running…" and each step shows its status.
3. On a listing with photos the status soon reads "Waiting for a person to review." The Human review step names what waits (photo suggestions, policy findings); Add to search and Estimate value stay "Not started".
4. Submit the listing for review, then sign in as `sunrise.admin@demo.example.com` and try to approve it: refused with "The workflow on this listing has not finished and waits for a review."
5. Decide every photo suggestion (agent) and every policy finding (admin). Within a few seconds the run goes on by itself and reads "Finished." Approval now works.
6. On a listing without photos the run finishes without pausing; Read the photos shows "Skipped" with the reason.
7. Start a run and click "Cancel run": the status reads "Cancelled". Click "Retry run": finished steps are kept and the rest run again.
8. Open "Monitor" in the nav. "Not finished" lists runs still going; switch to "Failed" or "All". As `sunrise.admin@demo.example.com` a "Failed background jobs" list with "Retry job" appears below; agents do not see it.
9. Sign in as `harbour.admin@demo.example.com` and open a Sunrise listing that is shared: there is no Workflow section, and Monitor shows no Sunrise runs.

### 6.13 API checks

The interactive docs at http://localhost:8000/api/v1/docs can call every endpoint. Sign in with `POST /api/v1/auth/login` there first; the session cookie is then used for the other calls. From a terminal:

```bash
curl -s -c /tmp/mls.cookies -H 'Content-Type: application/json' \
  -d '{"email":"sunrise.admin@demo.example.com","password":"local-dev-password"}' \
  http://localhost:8000/api/v1/auth/login
curl -s -b /tmp/mls.cookies 'http://localhost:8000/api/v1/listings?limit=5'
curl -s -b /tmp/mls.cookies 'http://localhost:8000/api/v1/audit-events?limit=10'
```

The audit log has no screen yet; read it through `GET /api/v1/audit-events` as an administrator. API conventions (error envelope, `X-Organisation-ID`, `version` for edits, cursor pagination) are in the README.

### 6.14 Phone width

In Chrome DevTools, device toolbar, 375 px wide. The pages do not scroll sideways; wide tables scroll inside their own box; forms are one column.

## AI with a real key

Put `GEMINI_API_KEY=...` in `.env` and restart the API and the worker. Get a key at https://aistudio.google.com/apikey. The free tier may use what you send to improve Google's models, so upload demo photos only. Photos are sent without camera or GPS data. Decisions about the provider are in `docs/decisions/0004-*.md` and `0005-*.md`.

Semantic search stays on the demo embedder until you also set `EMBEDDER=gemini`, because switching sends listing text to Google and re-embeds every listing. After switching (or after changing `VECTOR_STORE`), restart the API and the worker and run `cd services/api && .venv/bin/python -m app.modules.search.cli reindex`. Until the worker finishes, search returns only listings already embedded with the new model.

To use Qdrant instead of Postgres for vectors locally: `docker compose --profile qdrant up -d`, set `VECTOR_STORE=qdrant` in `.env`, restart, re-index. For Qdrant Cloud set `QDRANT_URL` (https) and `QDRANT_API_KEY`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| API exits at start with a settings error | `.env` missing or a value malformed. `cp .env.example .env`. |
| `connection refused` on 5432 | Postgres not running: `docker compose up -d --wait`. Another Postgres on 5432: set `POSTGRES_PORT` and the port in `DATABASE_URL` in `.env`. |
| Photos stay "Processing", AI runs stay queued, locations stay "Finding this address" | The worker (terminal 2) is not running. |
| Seeded properties made before Sprint 12 have no location | Run the seed again: it queues a lookup for them. |
| "Describe the home" finds nothing, or misses listings made before Sprint 13 | Worker not running, or the listings were never indexed. Run the seed again (it queues indexing for old demo listings) or `python -m app.modules.search.cli reindex`. |
| A check fails with `No handler registered for job kind ...` | A worker started before you pulled new code took the job. Stop every old `python -m app.worker` process, start one again, then run the check again. |
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
