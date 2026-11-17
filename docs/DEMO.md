# Demo script

A guided tour of every required feature, about 30 minutes, in the order a reviewer would meet them: a listing's whole life from draft to sold, the AI help along the way, the people who check it, and the platform around it. Each step says what to do and what the audience should see.

For an exhaustive test of each feature with edge cases, use [HOW_TO_RUN.md](HOW_TO_RUN.md) section 6. Architecture, workflow and data diagrams are in [architecture.md](architecture.md); limits in [known-limitations.md](known-limitations.md).

## Before you start

**Where:** the live demo URL (`https://<your-project>.vercel.app`, see [deployment/vercel.md](deployment/vercel.md)) or a local run (http://localhost:5173, [HOW_TO_RUN.md](HOW_TO_RUN.md) sections 2 and 3).

**Password:** every demo account uses the same password.

| Where | Password |
|---|---|
| Local | `local-dev-password` |
| Live demo | The `SEED_PASSWORD` value in the Vercel project (Settings > Environment Variables). It is deliberately not in the repository; ask the person who deployed it. |

**Accounts** (fictional; all data marked `[Demo]` is invented):

| Email | Role | Shows |
|---|---|---|
| `sunrise.agent@demo.example.com` | Agent, Sunrise Realty | Creating and editing own listings, photos, AI help, import, workflow |
| `sunrise.admin@demo.example.com` | Brokerage administrator, Sunrise Realty | Approving listings, policy review queue, members, API keys, webhooks, audit log |
| `harbour.admin@demo.example.com` | Brokerage administrator, Harbour Homes | A second organisation: sees only what Sunrise shares |
| `two.orgs@demo.example.com` | Broker at Sunrise Realty, agent at Harbour Homes | Switching organisation; second reviewer for appeals |
| `mls.admin@demo.example.com` | MLS administrator, Demo MLS | An MLS-level organisation |
| `platform.admin@demo.example.com` | Platform administrator | All organisations, service health, password reset links |

**Background jobs must be running:** the worker locally (`python -m app.worker`), or on Vercel a scheduler calling the job runner every minute ([deployment/vercel.md](deployment/vercel.md#background-jobs)). Locally a job starts within seconds; on Vercel within a minute, so say "this runs in the background" and move on, then come back.

**AI:** without `GEMINI_API_KEY` every AI result is labelled `[Demo]` and comes from a demo provider. Say so; that label is a feature (nothing pretends to be real AI). With a key, Gemini answers and takes 15 to 40 seconds.

Open a second browser window (or a private window) so two people can be signed in at once.

## Act 1. An agent lists a home (5 min)

Sign in as `sunrise.agent@demo.example.com`.

1. **Home.** The Overview shows my listings and Sunrise Realty's by status, workflows and unread notifications. No admin tiles: the screen follows the role.
2. **Listings > New listing.** Property type apartment; Address line 1 `21 Lake Road`; Locality `Powai`; City `Mumbai`; State `Maharashtra`; Postal code `400076`; Bedrooms `3`; Area `1250` sq ft; Title `[Demo] Lake-view 3 BHK`; Listing for sale; List price `25000000` INR; Visibility network; Remarks `Bright corner flat with a lake view, close to schools.` "Create draft listing". The listing opens as **Draft**, with "Created as Draft" in its status history. Prices show in rupees (₹2.5 Cr style).
3. **Location** (background job). The section soon shows the point in Powai with "Accurate to the area" and its source ("demo geocoder", or OpenStreetMap). Press "Set the point by hand", click the map, "Save point": it now says "Accurate to the building. Source: set by hand".
4. **Edit** the price to `24500000` and save. Mention the `version` check: if two people edit at once, the second is told and shown both versions (Act 6).
5. **Import** (Listings > Import listings): "Download a template" shows the accepted headers. A CSV from a portal with `BHK`, `₹1.25 Cr` and `Rs. 1,50,000` is understood, rows are checked before anything is saved, and each imported listing says which file and row it came from ([HOW_TO_RUN.md](HOW_TO_RUN.md) 6.8 has a ready-made file).

## Act 2. AI helps, people decide (8 min)

Still the agent. Open `[Demo] Compact studio to let` (a Sunrise draft with two demo photos).

1. **Photos.** Upload a JPEG or PNG of a room (no people in it). A progress bar, "Processing", then a thumbnail. A `.txt` file is refused with a message saying what is allowed.
2. **AI suggestions.** "Analyse photos". The run goes queued, running, succeeded. Each suggestion names the photo it came from and how sure it is; uncertain ones say so. Accept one, edit one, reject one. Accepted values appear under "Confirmed features". Point out that the listing's own fields did not change: AI never writes what the agent entered.
3. **Privacy redaction.** On a photo, "Check for sensitive content". The original with found areas outlined appears beside a blurred copy; the original is unchanged. Without a key, faces are checked locally and plates, phone numbers, watermarks and signs are listed as "not checked" with the reason, never silently skipped. "Approve copy".
4. **Semantic search.** Listings page, "Describe the home": `apartment near the lake`. `[Demo] 3 BHK apartment near the lake` comes first, and the "Why it matched" column gives the score and the shared words. Add the filter City `Pune` and search again: only Pune listings are ranked.
5. **Map.** "Show map": listings as markers; zoom to Mumbai and "Search this area".
6. **Valuation.** Open `[Demo] 3 BHK apartment near the lake`, "Estimate value". A range in rupees from 6 reported sales, the comparable sales table, a days-on-market scenario, and "Assumptions". It starts with "Not an appraisal…". Then open `[Demo] Garden villa` (Pune, no comparable sales) and press "Estimate value": "Insufficient data… No estimate is shown." No made-up number.

## Act 3. The workflow and the human check (7 min)

1. As the agent, open `[Demo] 2 BHK to let near the IT park` (pending review). Its remarks say "Vegetarians only, no bachelors." The **Policy check** section shows two findings: the phrase marked in its sentence, rule (food habits, marital status), severity, a suggested rewrite, and "Waiting for review". It says it is not a legal review and never says "compliant". The agent cannot decide findings.
2. Open `[Demo] Compact studio to let` again, **Workflow > Run workflow**. Each step shows its status: Locate, Read the photos, Policy check, Human review, Add to search, Estimate value. With photos, it soon reads **"Waiting for a person to review"** and names what waits.
3. "Submit for review" on the studio. The status becomes Pending review.
4. Sign in as `sunrise.admin@demo.example.com` in the other window. **Review queue** lists the IT-park findings, oldest first. Open the IT-park listing: finding 1 "Confirm issue"; finding 2 "Request edits" (stays disabled until a note is typed). Point out who decided and when.
5. Open the studio and try **"Approve and publish"**: refused with "The workflow on this listing has not finished and waits for a review." The gate is in the API, not just the button.
6. As the agent, decide every remaining photo suggestion on the studio. The run carries on by itself (within a minute on Vercel) and reads **"Finished."** Back as the admin, "Approve and publish": the studio is **Active**.
7. **Appeal:** as the agent, under the confirmed IT-park finding, enter a reason and "Appeal". As `sunrise.admin`, deciding it gives "Another reviewer must decide this appeal." As `two.orgs@demo.example.com` (broker at Sunrise), rule on it: the full trail of decision, appeal and ruling is shown.
8. **Monitor** (nav): runs that are not finished, failed, or all; administrators also see failed background jobs with "Retry job".

## Act 4. Publish, share, sell (4 min)

1. As the agent, open the `[Demo] Lake-view 3 BHK` from Act 1, "Submit for review". As `sunrise.admin`, "Approve and publish": **Active**, and visible to other organisations because its visibility is network.
2. Sign in as `harbour.admin@demo.example.com`. Sunrise's network listings are visible read-only, with no Workflow, Valuation or Team sections. Sunrise's private studio listing is not listed, and opening its URL gives "Listing not found".
3. As `two.orgs@demo.example.com`: the organisation switcher changes between Sunrise Realty and Harbour Homes, and the listings change with it.
4. As the agent, value the Lake-view listing ("Estimate value"), then "Mark as sold" with a sold price. After the next job run its valuation shows "Sold for … The estimate's middle was …% above/below it", which is how accuracy is tracked.
5. **Archive** a listing (inline confirm): it leaves the table. Its history stays in the audit log.

## Act 5. Working as a team (3 min)

1. As the agent on any own listing, **Team**: "Assign to" Sunrise's admin, post a comment, then save a "Private note".
2. As `sunrise.admin`, **Notifications** shows "… assigned you…". The listing shows the comment but not the private note. "Show activity" lists edits, status changes, workflow runs and comments, newest first.
3. **Edit conflict:** the same listing's edit page in both windows (agent and admin). Change the title in both, save the first, then the second: "Someone else saved this listing…" with a table of the differing fields, "Use theirs" or "Save mine over theirs".

## Act 6. Platform, API and operations (4 min)

1. As `sunrise.admin`: **Members**: invite by one-time link (no email is sent; the link is shown once), change a role. **Audit**: filter by Area "Listings" and a person; every action above is there with who and when.
2. **API keys:** create a key with both scopes and 5 requests per minute; it is shown once. From a terminal:

   ```bash
   MLS_API_URL=<app URL>/api/v1 MLS_API_KEY=<key> python3 examples/mls_client.py list
   ```

   It prints Sunrise's listings; quick repeats hit the rate limit (HTTP 429) and the client waits. "Revoke": the client gets `401 invalid_api_key`.
3. **Webhooks:** add one with a public receiver URL (locally `http://localhost:9099/` with `examples/webhook_receiver.py`, see [HOW_TO_RUN.md](HOW_TO_RUN.md) 6.12c), "Send test": the delivery is signed and shows "Delivered". Failed deliveries are retried 6 times and then listed under "Failed deliveries" with "Send again".
4. Sign in as `platform.admin@demo.example.com`, **Platform**: every organisation with "Work in it"; **Service health** with job, webhook and AI numbers and alerts in plain words ("Background jobs waiting over 5 minutes" if the job runner stops).
5. **Phone:** open the URL on a phone (or DevTools at 375 px). The navigation folds behind "Menu", tables scroll inside their box, nothing scrolls sideways. Chrome offers to install the app.
6. **Health:** `<app URL>/api/v1/health` gives `{"status":"ok","database":"ok"}`.

## If something goes wrong during the demo

| Symptom | What to do |
|---|---|
| Thumbnails stay "Processing", AI runs stay queued | The job runner is not being called. Locally start `python -m app.worker`; on Vercel check the scheduler, or call it once: `curl -H "Authorization: Bearer <CRON_SECRET>" <app URL>/api/v1/ops/run-jobs`. |
| A job failed | As `sunrise.admin`, Monitor > Failed background jobs > "Retry job". This is also the "recovery from a failed background task" check. |
| First page load on Vercel is slow | A cold start runs migrations; wait and reload. |
| Sign-in refused after many tries | The sign-in rate limit; wait a minute. |
