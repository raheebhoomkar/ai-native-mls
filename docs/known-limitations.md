# Known limitations and roadmap

This is a demo-ready build, not a production MLS. The limits that matter most are listed here; every sprint note (`docs/modules/s<N>-*.md`, "Known limitations") has the full list for its feature, and `shortcut:` comments in the code mark known simplifications with when to upgrade them.

## Not yet verified

- **Hosting:** the app has not run on Vercel (or Render) yet. The API image was built and run locally the way Vercel runs it; `vercel.json` is first read by Vercel at the first deployment.
- **CI on GitHub:** the dependency audit job and the backup-and-restore step have not run on GitHub; the same commands pass locally.
- **Live Gemini:** photo extraction was seen working once (S7). The redaction locator, the AI policy check and Gemini embeddings passed contract tests with recorded answers but were not seen working live (free-tier quota, 503s). Run `pytest -m live` with a key.
- **Accessibility:** keyboard, focus, labels and touch sizes are checked by tests and by hand; no automated scanner (axe) and no screen-reader pass.
- **Load:** a light smoke test (10 clients, reads only) on a laptop: 0 errors, p95 27 ms. Not run against the hosted app.

## Product limits

- **Policy checks** use an illustrative India policy written for the demo, not reviewed by a lawyer. English word rules only; other languages depend on the AI check. A check is decision support, never a statement that a listing is lawful.
- **Valuation** uses only sales prices that agents report when they mark a listing sold; nothing is verified, and the seeded comparable sales are invented. Condition, floor, age and amenities are not used. Not an appraisal.
- **AI results** without `GEMINI_API_KEY` come from labelled demo adapters: the demo embedder matches words, not meaning; the demo geocoder knows only some city and locality centres; redaction checks faces only.
- **Face detection** (OpenCV Haar) misses small, tilted or partly hidden faces.
- **Photos:** originals keep their EXIF data, including any GPS position, and anyone who can see the listing can download them (copies sent to AI providers and redacted copies have none). No photo order, cover photo or captions. 4 MB per photo on Vercel, 10 MB elsewhere.
- **Import:** CSV only (UTF-8, commas), up to 1,000 rows, no update of already-imported listings. Dates are read day first.
- **Neighbourhood data** (metro, schools, flood risk) has no source; it says "Not available" instead of inventing values.
- **No email or push:** invitations and password-reset links are shown once to an administrator; notifications are in the app only.
- **API keys** act as the person who created them (no service accounts) and cannot be rotated in place; webhook secrets neither.
- **Lists** such as the review queue, the monitor and activity timelines show the newest 50 to 100 items without paging.

## Operations limits

- **Background jobs on Vercel** run when a scheduler calls the job runner; with a scheduler every minute a job starts up to a minute late, and on the Hobby plan Vercel's own cron runs only once a day (`docs/deployment/vercel.md`).
- **No alerting** by email or paging: alerts are log fields and the Platform page. A log drain and an uptime check have to be set up on the host.
- **Backups** are by hand (`scripts/backup.sh`); uploaded photos are not in the database backup.
- **Map tiles** come from OpenStreetMap's public servers (light use only); Nominatim allows one request per second.
- Webhook delivery rows and sign-in session rows are never deleted.
- Demo accounts share one password, including the demo platform administrator.

## Roadmap

In rough order of value for a real pilot:

1. **Deploy and verify:** first Vercel deployment, the job runner every minute, the Playwright journeys against the live URL, a log drain and uptime check, scheduled backups (Neon point-in-time restore or a scheduled `backup.sh`).
2. **Real data sources:** a lawyer-reviewed policy pack per state; verified sold prices (registration data) for valuation; a neighbourhood data provider; a commercial map tile provider.
3. **Privacy:** strip EXIF and GPS from originals at upload; per-organisation redaction policy.
4. **Notifications:** email for invitations, password resets, assignments and review requests.
5. **Integrations:** service-account API keys with rotation, webhook secret rotation, RESO Web API compatibility, bulk import as a background job with progress.
6. **Scale:** pgvector or Qdrant for search past about 20,000 listings, a shared geocoding rate limiter, paging everywhere.
7. **Deferred infrastructure** (Kafka, Temporal, a graph database and others) only when the triggers in ADR 0006 are met.
