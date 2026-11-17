# How to run and test the app

This guide is for anyone who clones the repository, and for the AI coding assistant they use. It says how to start the app, which accounts to sign in with, how to run the automated checks, and how to test every feature by hand with the result you should see.

**To show the app to someone**, follow the guided [demo script](DEMO.md) (about 30 minutes, every required feature, with the demo accounts). **To deploy it**, see [deployment/vercel.md](deployment/vercel.md). Architecture and diagrams: [architecture.md](architecture.md). Limits and roadmap: [known-limitations.md](known-limitations.md).

Commands are for macOS or Linux. Run them from the repository root unless a step says otherwise. Each step lists what you should see; if you see something else, check [Troubleshooting](#troubleshooting).

## What is built

All 23 sprints of the plan (S0 to S22, Phases A to D) are done. Per-sprint notes, with design decisions and known limitations, are in `docs/modules/s<N>-*.md`; the newest one (`s22-handover.md`) has the final report.

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
| Public API | Create API keys with scopes and a rate limit; call the API from another program with a key; safe retries with `Idempotency-Key` | `s17-public-api.md`, `docs/api/developer-guide.md` |
| Webhooks | Send signed events (listing changed, property changed, workflow finished) to another system; see each delivery, send again | `s18-webhooks.md` |
| Team and notifications | Assign a listing to a teammate, comment or keep private notes, see the listing's activity; notifications with preferences; see both versions when someone saved first | `s19-collaboration.md` |
| Dashboard, audit log, app shell | Home page overview that matches your role; audit log with filters; Platform page lists organisations; phone menu, skip link, offline banner; install as an app (production build) | `s20-ux-admin.md` |
| Hosting and handover | Deploy to Vercel (web on the CDN, API as a container, jobs through a protected job-runner URL); demo script, architecture, workflow and data diagrams, limits and roadmap, handover checklist | `s22-handover.md` |
| Operations | Service health on the Platform page (jobs, webhooks, AI failures, alerts); failed webhook deliveries across all webhooks; daily cleanup; backup, restore and restore check; load smoke test; dependency scanning in CI. Runbooks: `docs/operations/runbooks.md` | `s21-hardening.md` |
| Editorial Luxury design | Whole app restyled (ivory, espresso and bronze, serif headings): sidebar navigation that folds into a drawer on phones, image-led listing grid with a table view, listing pages with a photo hero, specifications and agent card, AI tags and confidence meters on AI output, subtle animations | `s23-editorial-redesign.md` |

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

On a deployed demo the same accounts exist, but their password is the `SEED_PASSWORD` value set in the host (Vercel: Settings > Environment Variables). It is deliberately not in the repository.

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

Expected on 2026-11-17 (end of S22): API 342 passed, 3 deselected (the deselected ones are live Gemini tests); web 90 passed; Playwright 9 passed and 1 skipped against the dev server, 10 passed against the production build. Higher counts later are fine; any failure is not.

Live Gemini tests (need `GEMINI_API_KEY`, use free-tier quota): `cd services/api && .venv/bin/pytest -m live`.

Browser end-to-end tests (app and worker running as in step 3, seed loaded, Chrome installed):

- `journey.e2e.ts`: an agent signs in, creates a listing, finds it, submits it for review and archives it.
- `workflow.e2e.ts`: an agent runs the workflow on a new listing, comments, sees the run on the Monitor and archives the listing.
- `console.e2e.ts`: the dashboard for an administrator and an agent, audit filters, the Platform page, the skip link, phone (390 px) and tablet (768 px) layouts, the offline banner, and the app opening offline. The last one runs only against a production build and is skipped on the dev server.

```bash
cd apps/web && pnpm e2e
# against the production build served by the API (no dev server):
cd apps/web && pnpm build && cd ../../services/api \
  && WEB_DIST_DIR=../../apps/web/dist .venv/bin/uvicorn app.main:app --port 8001
cd apps/web && E2E_BASE_URL=http://localhost:8001 pnpm e2e   # in another terminal
```

CI (`.github/workflows/ci.yml`) runs the same API and web checks on pull requests, plus a dependency audit (`pip-audit`, `pnpm audit --prod`) and a backup-and-restore check after the browser journeys.

Operations checks (Postgres running; the second needs the API on port 8000 and the seed):

```bash
DATABASE_URL=postgresql://mls:mls@localhost:5432/mls scripts/backup_restore_check.sh
python3 scripts/load_smoke.py --email sunrise.agent@demo.example.com --password local-dev-password
```

Expected: "Restore check passed: <n> tables, same row counts." and a summary line with 0 errors. Details and the restore procedure: `docs/operations/runbooks.md`.

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

### 6.12b API keys and the sample client

1. Sign in as `sunrise.admin@demo.example.com`, open "API keys", name a key, tick both scopes, set 5 requests per minute, click "Create key". The key appears once in a notice; copy it.
2. In a terminal from the repository root: `MLS_API_URL=http://localhost:8000/api/v1 MLS_API_KEY=<key> python3 examples/mls_client.py list` prints up to 10 Sunrise listings. `... create` prints "Created draft listing <id>"; it shows in the app as a draft.
3. Run `list` several times quickly: after 5 requests in a minute the client waits about a minute (HTTP 429) and then prints the list.
4. Back on "API keys" the key shows its use this minute and when it was last used. Click "Revoke": the client now exits with `HTTP 401 invalid_api_key`.
5. Sign in as `sunrise.agent@demo.example.com`: there is no "API keys" link.

### 6.12c Webhooks (worker must be running)

1. Sign in as `sunrise.admin@demo.example.com`, open "Webhooks", enter `http://localhost:9099/`, tick "A listing is created or changed" and "A listing workflow finishes…", click "Add webhook". Copy the secret from the notice.
2. In a terminal from the repository root: `MLS_WEBHOOK_SECRET=<secret> python3 examples/webhook_receiver.py 9099`.
3. Click "Send test". Within a few seconds the terminal prints `signature ok: ping …`. "Show deliveries" lists it as "Delivered", 1 attempt.
4. As `sunrise.agent@demo.example.com`, edit a listing or run its workflow. The terminal prints `signature ok: listing.changed …` (and `workflow.finished …` when the run ends).
5. Stop the receiver (Ctrl+C) and edit a listing again. The delivery shows "Trying" with the next attempt time and the error. Start the receiver again: the next attempt is delivered. After 6 failed attempts it shows "Failed" and "Send again".
6. Click "Turn off": no more deliveries are sent, and "Send test" disappears.

### 6.12d Team, notifications and edit conflicts

1. Sign in as `sunrise.agent@demo.example.com`, open one of your listings. The "Team" section shows "Assigned to: nobody besides the listing agent".
2. Choose "Assign to" a teammate (for example Sunrise's admin) and click "Assign". Post a comment, then tick "Private note" and save a note.
3. Sign in as `sunrise.admin@demo.example.com`. The "Notifications" link shows a count; the page lists "… assigned you: …". Open the listing: the team comment shows, the private note does not. Reply with a comment.
4. Back as the agent, the reply is in Notifications. Untick "Someone comments on a listing I work on" and ask the admin to comment again: no new notification.
5. "Show activity" on the listing lists edits, status changes, workflow runs and comments, newest first.
6. Edit conflict: open the same listing's edit page in two browser windows (agent and admin). Change the title in both; save in the first, then in the second. The second shows "Someone else saved this listing…" with a table of the fields that differ. "Use theirs and discard mine" loads their version; "Save mine over theirs" saves yours on top.
7. Sign in as `harbour.admin@demo.example.com` and open a shared Sunrise listing: there is no Team section.

### 6.13 API checks

The interactive docs at http://localhost:8000/api/v1/docs can call every endpoint. Sign in with `POST /api/v1/auth/login` there first; the session cookie is then used for the other calls. From a terminal:

```bash
curl -s -c /tmp/mls.cookies -H 'Content-Type: application/json' \
  -d '{"email":"sunrise.admin@demo.example.com","password":"local-dev-password"}' \
  http://localhost:8000/api/v1/auth/login
curl -s -b /tmp/mls.cookies 'http://localhost:8000/api/v1/listings?limit=5'
curl -s -b /tmp/mls.cookies 'http://localhost:8000/api/v1/audit-events?limit=10'
```

The audit log is also on the Audit page (section 6.15). Filters: `action` (prefix, such as `listing.`), `actor_user_id`, `target_id`. API conventions (error envelope, `X-Organisation-ID`, `version` for edits, cursor pagination) are in the README.

### 6.14 Phone width

In Chrome DevTools, device toolbar, 375 px wide. The pages do not scroll sideways; wide tables scroll inside their own box; forms are one column. The navigation folds behind a "Menu" button and slides in from the left; choosing a page, or tapping outside it, closes it.

### 6.15 Dashboard, audit log and app shell

1. Sign in as `sunrise.agent@demo.example.com`. Home shows an "Overview": My listings and Sunrise Realty listings by status, Workflows, Unread notifications. There is no review queue tile, no Administration tile and no Audit link.
2. Sign in as `sunrise.admin@demo.example.com`. Home also shows "Policy findings to review", "Failed background jobs" and an Administration tile (Members, API keys, Webhooks, Audit log). Each link opens its page.
3. Audit: choose Area "Listings", then a Person. Only their listing events remain. Paste a listing ID into "Record ID" to see everything about that listing. Sign-in events belong to no organisation, so they are not listed here.
4. Sign in as `platform.admin@demo.example.com` and open Platform. The Organisations table lists every organisation; "Work in it" switches to one and shows its Home.
5. Keyboard: reload the page and press Tab. "Skip to main content" appears top left; Enter moves focus past the navigation. Every control can be reached with Tab and shows a focus outline.
6. Offline: in DevTools, Network, choose "Offline". A dark banner says you are offline, and actions fail with "You are offline. Try again when the connection is back." Switch back to "No throttling": the banner goes.
7. Install (production build only, see "Running the production image locally"): Chrome's address bar should offer "Install" (not yet checked by hand). After one visit, the app opens with the network off and says it is offline.

### 6.16 Operations (worker must be running)

1. Sign in as `platform.admin@demo.example.com` and open Platform. "Service health" lists anything that needs attention (or "No problems found.") and the numbers for background jobs, webhook deliveries and AI extraction. "Check again" reloads them.
2. Stop the worker, then upload a photo as `sunrise.agent@demo.example.com`. After 5 minutes, "Check again" on the Platform page shows "Background jobs waiting over 5 minutes". Start the worker: the alert goes once the job has run.
3. Webhooks dead letters: follow 6.12c up to step 5 and let all 6 attempts fail (about 15 minutes). As `sunrise.admin@demo.example.com`, the Webhooks page's "Failed deliveries" table lists it with the webhook URL. Start the receiver and click "Send again": it is delivered.
4. Worker log: at most once a day (checked when the worker starts and every hour), it logs "Cleanup finished" with the number of rows deleted.

### 6.17 Job runner over HTTP (how jobs run on Vercel)

1. Stop the worker (terminal 2). Add `CRON_SECRET=local-cron-secret-123` to `.env` and restart the API.
2. As `sunrise.agent@demo.example.com`, upload a photo. It stays "Processing".
3. `curl -s http://localhost:8000/api/v1/ops/run-jobs` gives 401 `invalid_cron_secret`. With the secret: `curl -s -H "Authorization: Bearer local-cron-secret-123" http://localhost:8000/api/v1/ops/run-jobs` gives `{"ran":<n>}` and the thumbnail appears on the next refresh.
4. Remove `CRON_SECRET` from `.env` and restart: the route answers 404. Start the worker again.

### 6.18 Editorial design

1. Sign-in page: a dark panel with the product statement and a line drawing beside the sign-in card. On a phone the panel shrinks to a band above the card.
2. Sign in as `sunrise.agent@demo.example.com`. A sidebar on the left holds the organisation, the pages this role may open (grouped Workspace, Administration, Account) and the person with "Sign out". Home greets you by first name and shows the overview tiles, a "Needs your attention" list built from the numbers, the latest listings as cards and recent notifications.
3. Listings: cards with the first photo (or a line drawing when a listing has none), status, price, place and key facts. "Grid" and "Table" switch the layout; the choice is remembered in this browser. "Describe the home" carries a "Semantic search" tag.
4. Open "[Demo] 2 BHK to let near the IT park". The photos fill a hero at the top; "All 2 photos" scrolls to the gallery. Below: title, status, list price, a row of specifications, details on the left, and the agent card, "Manage listing" and "AI suggestions" on the right (above the details on narrow screens). AI panels show a bronze tag; suggestions and policy findings show a confidence meter beside the percentage.
5. Motion: pages fade up on navigation, cards lift on hover, photos zoom slowly. With the system setting "Reduce motion" on, these stop.
6. API: every listing in `GET /api/v1/listings` and `GET /api/v1/listings/{id}` has `cover_url`, a signed, short-lived link to the thumbnail of its first photo, or `null`.

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
| `Multiple head revisions are present` from Alembic or pytest | Copies of migration files named `* 2.py` (iCloud conflict copies) are in `services/api/migrations/versions`. Move them out of the repository. |
| `alembic check` reports changes | A model changed without a migration. `alembic revision --autogenerate -m "..."`, review it, `alembic upgrade head`. |

## Running the production image locally

- Vercel's API image (`services/api/Dockerfile`, API only): "Running the API image locally" in `docs/deployment/vercel.md`.
- Render's image (repository-root `Dockerfile`, API plus the built web app on one port): "Running the same image locally" in `docs/deployment/render.md`.

## Notes for AI assistants working on this repository

- Do not commit files named `* 2.*`: they are iCloud conflict copies, and copies of migration files make Alembic report several heads.
- Start here, then read the newest `docs/modules/s<N>-*.md`. Its status line, chunk checklist and "Next" section say what is done and what is next. Each finished sprint's "Shared pieces later sprints must reuse" table lists the code to reuse.
- To verify the app: run section 5, then walk section 6 in a browser. Report each step as passed or failed with what you saw. Do not report a step as passed without running it.
- Use only the seeded `[Demo]` data and demo photos. Do not upload real people's photos or real listings, and do not send them to Gemini.
- The API is the source of truth for permissions. The web app hides controls by `my_permissions`, `can_edit` and `allowed_transitions`, never by role name.
- AI output is a suggestion. It never writes agent-entered listing fields; a person decides. Compliance results are decision support under an illustrative policy, never a statement that a listing is legally compliant.
- After changing the API, run `pnpm gen:api` in `apps/web`. After changing a model, add an Alembic migration.
