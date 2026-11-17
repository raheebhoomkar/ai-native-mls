# Sprint 14: Valuation and simulation (Module 9)

**Status: done (2026-11-17).** All four chunks are finished. This closes Phase B. Staged, not committed.

Branch: `feature/s6-media-jobs`. Claude does not commit or push; the developer does.

Scope (from the approved plan, Module 9): comp selection on geography, type, area, date and condition; a baseline valuation with range and sample size; a seeded, reproducible Monte Carlo for days on market; asking and closed prices kept apart; an "insufficient data" state; a "not an appraisal" disclaimer; model and parameter versioning; prediction versus later outcome.

## Design decisions (reversible; made 2026-11-17)

- **Module** `app/modules/valuation/`. Computed synchronously on request (no model call, no job), stored in a `valuations` table with `model_version`, `parameters` (every assumption, including the seed) and `result`.
- **Comps are reported closed sales only.** Listings with status `sold` and a `sold_price_amount` that the caller may see (the S3 visibility rule, through `listings.service.filtered_listings`). The closed price is recorded by the listing agent and not verified; every screen says so.
- **Asking prices are separate.** Active listings matching the same rules are summarised beside the estimate as "asking prices, not sale prices" and never enter it.
- **Comp rules** (defaults, sent back as assumptions): same property type, same sale or rent; within `radius_km` 5 of the subject when it has a point, else the same city and locality; area within 30 % (sqm converted to sqft); bedrooms within 1; closed within the last 24 months. Closest first, then most similar area, then newest; at most 10. Condition is not recorded anywhere, so it is not used, and the result says so.
- **Baseline** `baseline-ppsf-v1`: median price per sqft of the comps times the subject's area; range from the 25th to 75th percentile. Without a subject area: median closed price with the same percentiles. Fewer than 3 comps: `insufficient_data` with the reason, and no number.
- **Days-on-market simulation** `dom-lognormal-v1`: a lognormal fitted to the comps' days from listed to closed, 2000 runs with a stored seed (`random.Random(seed)`), so the same seed and comps give the same answer. Needs 5 comps with both dates; otherwise "not available" with the reason. Offer outcomes: not available, because no offers are recorded.
- **Who**: readers (`listing:read`) in the organisation that owns the listing. Another organisation gets 404, even on a shared listing. Requests are audited as `valuation.requested`.
- **Outcome tracking**: the S13 outbox. `listing.changed` gets a `valuation.outcome` job; when the listing is sold, its earlier valuations get `outcome_price` and `outcome_at`. `GET /valuations/evaluation` reports, per model version, the count, median absolute percentage error and share of sales inside the range.

## Chunks

- [x] **1. Backend.** Model, migration, comp selection, baseline, simulation, outcome job, API, tests.
- [x] **2. Seed.** Sold demo listings with backdated listed and closed dates near Powai, so the demo has comps.
- [x] **3. Web.** "Valuation" section on the listing page. Tests.
- [x] **4. Browser check and docs.**

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/alembic check && .venv/bin/pytest -q
# from apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log
- 2026-11-17: chunk 1. `app/modules/valuation/` (models, schemas, service, router), migration `a5f3d2b8e110`, `tests/test_valuation.py` (5 tests). `created_at` is set in Python so two valuations in one transaction keep their order.
- 2026-11-17: chunk 2. Seed adds six `[Demo] Sold:` Powai apartments with backdated listed and closed dates (seed only).
- 2026-11-17: chunk 3. `ListingValuation.tsx` on the listing page (owning organisation only), `ListingValuation.test.tsx` (3 tests).
- 2026-11-17: chunk 4. Browser check at desktop and 375 px on the `mls_e2e` database; docs.

## What was built

- API: `POST /api/v1/listings/{id}/valuations` (body: optional `seed`, `radius_km`, `months`, `area_tolerance`, `bedrooms_tolerance`) returns the stored valuation; `GET` on the same path lists the 20 newest; `GET /api/v1/valuations/evaluation` gives per-model accuracy on listings that later sold.
- Each valuation: status (`ok` or `insufficient_data`), the estimate range and middle, sample size, oldest and newest comp closing dates, every comp (price, closing date, days on market, distance, area, price per sq ft, organisation, price source), asking prices of active comparables apart from the estimate, a days-on-market simulation, why offers are not simulated, the assumptions in words, the parameters (with seed), model and simulation versions, the disclaimer, and the later sale if there was one.
- Web: "Valuation" section on the listing page with "Estimate value", the range, comps table, simulation, asking prices and an "Assumptions" list.
- Audit: `valuation.requested` with the valuation ID, status, versions and seed.

## Acceptance results

- Output shows its comps and assumptions (`test_estimate_from_comparable_sales_with_assumptions`; browser).
- No unsupported number is shown as fact: under 3 comps there is no estimate, only the reason; under 5 dated comps no simulation; offers never simulated; the simulation is called "a scenario, not a forecast".
- Insufficient data returns a clear state (`test_too_few_comps_is_insufficient_data_with_no_number`).
- Simulation is reproducible for a stored seed (`test_simulation_needs_enough_samples_and_is_seeded`, and the API test re-runs seed 7).
- Model version, parameters and later outcomes are recorded; `GET /valuations/evaluation` reports the error (`test_later_sale_is_recorded_as_the_outcome_and_evaluated`).
- Another organisation's private sales are never comps; another organisation cannot value or read valuations of a shared listing (404).
- All checks pass: API ruff, mypy, alembic check, pytest (301); web lint, typecheck, test (68), build.

## Known limitations

- Comps are only as good as what agents report when marking a listing sold; nothing is verified. Seeded comps are invented.
- Condition, floor, age and amenities are not used (not recorded, or not structured). No semantic or photo similarity in comp selection yet; S13's vector store could add it.
- The range is the comps' 25th to 75th percentile of price per sq ft, not a confidence interval. With few comps it can be narrow.
- The simulation assumes days on market are lognormal and that the past comps represent this listing; it ignores price changes and season.
- Evaluation counts every valuation made before a sale, so repeated valuations of one listing weigh more.
- Looks at most 500 filter matches per status (`shortcut:` in `valuation/service.py`).

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| Valuation as a workflow step (S15) | `valuation.service.request_valuation(session, ctx, listing_id, ValuationRequest(...))`; deterministic, no job needed |
| Area in sq ft whatever the unit | `valuation.service.area_sqft(prop)` |
| React to a listing selling | subscribe to `listing.changed` like `valuation.outcome` does |

## Next

Phase B is complete. Stop for the Phase B report and the developer's feedback before Phase C (S15 workflow core).
