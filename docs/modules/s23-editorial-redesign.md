# S23: Editorial Luxury redesign

Status: done, staged, not committed. Requested 2026-11-17 after S22: restyle the whole web app in an "Editorial Luxury" theme (warm ivory, espresso, bronze, serif headings) with animations, without changing behaviour, APIs, routes or RBAC.

## Rules for this sprint

- Behaviour stays the same. Every route, API call, permission check and accessible name that tests use stays as it was.
- Design tokens live at the top of `apps/web/src/index.css`. Components use the tokens, never raw colours.
- Shared UI pieces (icons, AI tag, confidence meter, status pill) live in `apps/web/src/ui.tsx`.
- No new npm dependencies. Fonts come from Google Fonts (Playfair Display, Inter) with serif and sans fallbacks.
- Animations respect `prefers-reduced-motion`.
- Muted text uses `--ink-muted` (#6B635A), not the brief's #81796F, which is below 4.5:1 on ivory. Bronze text uses `--bronze-ink` for the same reason.

## Chunks

- [x] 1. API: `cover_url` on every listing (signed thumbnail of the first photo), test in `tests/test_media_processing.py`, schema regenerated.
- [x] 2. Design tokens and global stylesheet; fonts; theme colour.
- [x] 3. Shared UI (`ui.tsx`); app shell with sidebar and phone drawer; sign-in and public link pages.
- [x] 4. Home and dashboard: welcome header, KPI tiles, status chart, attention list, recent listings, activity.
- [x] 5. Listings: image-led grid with table view toggle; filters.
- [x] 6. Listing detail: photo hero, header with price, specs, two columns, panels.
- [x] 7. Forms, AI panels (AI tag, confidence), admin pages.
- [x] 8. Unit tests, lint, typecheck, build, end-to-end tests, screenshots of every role; docs.

## What changed

- `apps/web/src/index.css`: rewritten as a token-based design system (palette, fonts, radii, shadows, easing at the top). All existing class names kept and restyled; new ones for the shell, cards, panels, hero and states.
- `apps/web/src/ui.tsx` (new): `Icon` (inline SVG set), `BrandMark`, `Brand`, `Arches`, `PlaceholderArt`, `AiTag`, `Confidence`, `initials`.
- `App.tsx`: sign-in and one-time link pages use `AuthFrame`; a branded splash while the session loads.
- `Workspace.tsx`: sidebar shell (`.shell`, `.sidebar`, `.topbar`, `.scrim`) with grouped, role-aware navigation; `Home` component; each route change animates `.page` with the Web Animations API (skipped under reduced motion).
- `Dashboard.tsx`: status bar chart in the listing tiles, "Needs your attention" list, latest listings (cards) and recent activity (notifications). The two extra requests fail quietly.
- `Listings.tsx`: `ListingCard` (exported, also used on Home), grid or table view remembered in `localStorage` (`mls.listingView`), skeleton cards while loading, empty state.
- `ListingDetail.tsx`: photo hero from the gallery's media list (no extra request), header with price, specifications row, two columns (details and panels; agent card, Manage listing, AI suggestions).
- AI panels (`ListingSuggestions`, `ListingRedaction`, `ListingCompliance`, `ListingWorkflow`) get a `panel-head` with an `AiTag`; suggestions and findings get a confidence meter.
- API: `cover_url` on `ListingOut` (`media.service.cover_thumbnails`, one query per page of listings). Same signed thumbnail links the media list already gives anyone who may read the listing.
- Tests changed only where markup moved: listing rows are now cards (`closest("article")`), the phone menu `open` class is on the sidebar, and the end-to-end tests use the grid (and switch to the table once).

## Shared pieces later work must reuse

| Piece | Where |
|---|---|
| Colours, fonts, radii, shadows, timing | `:root` tokens in `apps/web/src/index.css` |
| Icons, AI tag, confidence meter, placeholder art | `apps/web/src/ui.tsx` |
| Status colour on any element | `status-pill status-<status>` or `data-status="<status>"` |
| Buttons | default is secondary; `type="submit"` or `.primary` is filled; `.danger`, `.ghost`, `.small`; links styled as buttons use `.button-link` |
| Page header | `header.page-head` with `.eyebrow`, `h2`, `.lede`, `.page-actions` |
| Card on a page | `.panel`; listing panels are styled automatically inside `.listing-main` and `.listing-aside` |
| Listing card | `ListingCard` in `Listings.tsx` |

## Known limits

- Fonts load from Google Fonts. Offline, or if blocked, the app falls back to Georgia and the system sans-serif.
- Cards use the 480 px thumbnail; on very wide screens they are slightly soft. The hero uses the original photo.
- The workflow end-to-end test could not finish on this machine: a worker with the real Gemini key kept taking AI jobs and hit the free-tier quota (`RateLimited`). Every other end-to-end test passed.

## Log

- Chunk 1 done: backend tests for media, listings, search and imports pass.
- Chunks 2 to 8 done in one go on 2026-11-17: 90 unit tests, lint, typecheck, build, 343 backend tests pass; end-to-end: 8 passed, 1 skipped (production build only), the workflow test failed on the Gemini quota (see Known limits). Screenshots checked for every role at 1440, 768 and 390 px.
