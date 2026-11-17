# Sprint 10: Standardisation and import (Module 6a)

**Status: done (2026-11-17).** All four chunks are finished. Staged, not committed.

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s10-import` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan and INSTRUCTIONS.md Module 6, first half): a canonical listing field set with RESO-aligned names (no conformance claim); a mapping layer that turns external field variants (column names and value formats) into canonical fields; import validation with field-level, actionable errors. Compliance flags are Sprint 11. No AI is used, so the Gemini quota does not matter here.

## Design decisions (reversible; made 2026-11-17)

- **Canonical fields** (`app/modules/imports/fields.py`): the fields the existing listing and property API already accepts. Each has a RESO Data Dictionary name where a close RESO field exists (`ListPrice`, `BedroomsTotal`, `LivingArea`...) and none where RESO has no equivalent (title, locality). Alignment only: no RESO version is targeted and no conformance is claimed, because INSTRUCTIONS.md §14 question 3 is unanswered.
- **Format**: CSV text (UTF-8, first row is the header), sent as JSON `{filename, content}`. At most 1,000 rows and 2,000,000 characters. Parsed synchronously; no job.
- **Header mapping**: headers are compared after lower-casing and removing everything except letters and digits, so `List Price`, `list_price` and `ListPrice` match. Each field accepts its own name, its RESO name and a fixed list of variants. Unknown columns are reported and ignored. Two columns for one field is a file error.
- **Value normalisation** (India first): prices with `₹`, `Rs`, `INR`, Indian digit grouping, `lakh`/`L` and `crore`/`Cr`; area with units in the value (`1,250 sq ft`) or a unit column, `sq yd` converted exactly (×9) to sq ft; property type synonyms (`Flat`, `Condominium`, `Independent House`, `Land`...); `Sale`/`Rent` synonyms; `3 BHK` as 3 bedrooms; dates as `YYYY-MM-DD` or Indian `DD/MM/YYYY`; country names to ISO codes. Missing currency is INR; missing country is IN.
- **Not mapped on purpose**: built-up and super built-up area (they are not the living area; only carpet area maps to `area`), visibility, listing agent.
- **Validation**: after normalising, every row is validated with the same Pydantic models as the listing API (`PropertyCreate`, `ListingCreate`), so an import can never store what the form would refuse. Errors name the canonical field, the source column, and say how to fix it.
- **All or nothing**: an import is refused if any row has an error; preview first, fix the file, then import. No partial imports, so fixing and re-importing cannot duplicate rows.
- **Duplicates**: a row's `ListingId` (external ID) already imported into the organisation, or repeated in the file, is a row error.
- **What an import creates**: a property and a `draft`, `private` listing per row, with the importer as listing agent. Nothing is shared or published until a person does it.
- **Provenance**: a `listing_imports` row per import (who, when, file name, counts) and an `listing_import_rows` row per created listing with its row number, external ID and the original cells of the recognised columns only (an unrecognised column such as "Owner phone" is never stored). The listing page shows "Imported from <file>, row N" with the original values. Another organisation viewing a shared listing never sees where it came from.
- **Permission**: `listing:write`. Audited as `listing.imported` (counts and import ID, no cell values).

## How to resume

1. `git status` and `git log --oneline | head -3`.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. Do the first unchecked chunk below. Run the checks, tick the chunk, add a line under "Log", stage.

## Chunks

- [x] **1. Fields, mapping and validation (backend, no database).** `app/modules/imports/fields.py` (canonical fields, header variants, value normalisers), `validation.py` (parse CSV, map headers, normalise, validate with the listing schemas, field-level errors). Unit tests with a test set of variant files.
- [x] **2. Persistence and API.** Models and migration (`listing_imports`, `listing_import_rows`), service (preview, import, list, get, listing source), router: `GET /api/v1/imports/fields`, `POST /api/v1/imports/preview`, `POST /api/v1/imports` (201), `GET /api/v1/listings/{id}/import-source` (null when not imported). A list of past imports was left out: the audit log already records each one. Router tests including permissions and other-organisation 404. `pnpm gen:api`.
- [x] **3. Web.** "Import listings" page from the listings page: choose a CSV, preview (column mapping, unknown columns, rows with errors highlighted by field), Import button only when there are no errors, result with links; field reference with a template download. "Imported from" line on the listing page.
- [x] **4. Acceptance.** Browser run, full checks, notes below.

## Checks

- `cd services/api && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy . && .venv/bin/pytest -q`
- `cd apps/web && pnpm lint && pnpm typecheck && pnpm test && pnpm build`

## Log

- 2026-11-17: plan and design written.
- 2026-11-17: chunk 1. `fields.py`, `validation.py`, three fixture files (`reso.csv`, `portal.csv`, `invalid.csv`), 27 unit tests.
- 2026-11-17: chunk 2. Models, migration `fbc1f17e77ed`, service, router, 7 API tests. `pnpm gen:api`.
- 2026-11-17: chunk 3. `ListingImport.tsx` (page, field reference, template download, `ImportSourceDetails`), route `/listings/import`, link on Listings, 3 web tests. Page tests now stub `/listings/l1/redactions` (missing since Sprint 9; an unstubbed call made one test timing-dependent).
- 2026-11-17: chunk 4. Browser run and full checks.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Accept listing data from outside (syndication in, a partner API, Sprint 18 webhooks) | `imports.validation.parse` for CSV, or the same normalisers in `imports.fields` for other shapes; validate with `PropertyCreate` / `ListingCreate`, never a second set of rules. |
| A new import format value (another unit, synonym, date style) | Add it to the table or normaliser in `fields.py` plus a case in `tests/test_imports_validation.py`. The header index raises at start-up if two fields claim one header. |
| Where an imported listing came from | `imports.service.get_source` (same organisation only). |
| Compliance scan of imported remarks (Sprint 11) | Imported listings are ordinary drafts; scan them like any listing. |

## Acceptance results

- Supported external field variants map to canonical fields: yes. RESO-named, Indian-portal-style and plain headers all map (tests); in Chrome, `portal.csv` showed "Ref No (as Listing ID)", "BHK (as Bedrooms)", "Carpet Area (sq ft) (as Area)" and prices 1,25,00,000 / 85,00,000 / 1,50,000 from "₹1.25 Cr", "85 lakh", "Rs. 1,50,000".
- Invalid fields produce actionable validation errors: yes. Each names the field and source column and says what to write instead ("\"Swap\" is not a listing type. Use sale or rent."); missing or doubled columns are file errors listing the accepted headers. Seen in Chrome with a broken file; the Import button stays hidden and the API refuses with 422 `import_invalid`.
- Imported data is provenance-tracked: file, row, Listing ID and original cells, shown on the listing page (Chrome: "portal.csv, row 3 (Listing ID P-102)"); audit `listing.imported`.
- Permissions: `api_consumer` gets 403 on fields, preview and import; another organisation gets 404 on a private listing's source and null on a shared one (tests).
- Narrow layout: at 375 px the page does not scroll sideways; the preview and field tables scroll inside their own box.
- Checks: ruff, format, mypy, `alembic check`, pytest (197 passed); web lint, typecheck, test (52 passed, 3 runs), build; Docker build.

## Known limitations

- CSV only, comma-separated, UTF-8. A file saved by Excel in another encoding or with semicolons is reported as having unknown columns rather than detected.
- Synchronous, at most 1,000 rows. A larger feed needs a job (Sprint 6 queue) and a progress page.
- Dates like 03/04/2027 are read day first (3 April), the Indian convention. An American-style file would be misread when the day is 12 or less.
- Built-up and super built-up area are not imported; there is one area field (living/carpet area).
- Every imported listing gets the importer as listing agent; assigning agents from a column is not supported.
- No update-by-import: a Listing ID already imported is refused, not updated.
- RESO names are alignment only; no RESO version is targeted (INSTRUCTIONS.md §14 question 3 is still open).

## Next

Phase B continues with Sprint 11 (compliance flags), 12 (geospatial) or 13 (semantic search); Sprint 14 needs 13. The plan's shortest path to a full demo goes to Sprint 11 then 13.
