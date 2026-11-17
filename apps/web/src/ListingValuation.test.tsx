import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ListingValuation } from "./ListingValuation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const money = (amount: string) => ({ amount, currency: "INR" });

const DISCLAIMER =
  "Not an appraisal and not a guaranteed sale price. Decision support from sales reported by listing agents, which are not verified.";

const valuation = (overrides: Record<string, unknown> = {}) => ({
  id: "v1",
  listing_id: "l1",
  status: "ok",
  model_version: "baseline-ppsf-v1",
  simulation_version: "dom-lognormal-v1",
  parameters: { seed: 42 },
  outcome: null,
  requested_by_user_id: "u1",
  created_at: "2026-11-17T10:00:00Z",
  disclaimer: DISCLAIMER,
  result: {
    currency: "INR",
    reason: null,
    estimate: {
      low: money("24000000.00"),
      median: money("25000000.00"),
      high: money("26000000.00"),
      method: "price_per_sqft",
      subject_area_sqft: 1250,
    },
    sample_size: 1,
    data_from: "2026-01-10",
    data_to: "2026-01-10",
    comps: [
      {
        listing_id: "c1",
        title: "[Demo] Sold: 3 BHK, Lake Homes",
        organisation_name: "Sunrise Realty",
        closed_price: money("23500000.00"),
        closed_on: "2026-01-10",
        listed_on: "2025-12-06",
        days_on_market: 35,
        distance_km: 0,
        area_sqft: 1180,
        price_per_sqft: "19915",
        bedrooms: 3,
        price_source:
          "Reported by the listing agent when marking the listing sold; not verified.",
      },
    ],
    asking: {
      count: 2,
      basis: "price_per_sqft",
      low: "19000",
      median: "20000",
      high: "21000",
      currency: "INR",
    },
    simulation: {
      available: true,
      runs: 2000,
      seed: 42,
      samples: 6,
      days_p10: 29,
      days_p50: 49,
      days_p90: 83,
      sold_within: { "30": 0.116, "60": 0.693, "90": 0.932 },
    },
    offers_reason:
      "Offers are not recorded in this MLS, so offer outcomes are not simulated.",
    assumptions: ["Condition is not recorded, so it is not used."],
  },
  ...overrides,
});

function stub(list: unknown[], created: unknown) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      return init?.method === "POST"
        ? Response.json(created, { status: 201 })
        : Response.json(list);
    }),
  );
  return calls;
}

test("shows the range, comps, simulation, asking prices apart and the disclaimer", async () => {
  stub([valuation()], null);
  render(<ListingValuation listingId="l1" />);

  expect(await screen.findByText(/From 1 reported sales/)).toBeTruthy();
  expect(screen.getByText(DISCLAIMER)).toBeTruthy();
  expect(screen.getByText("[Demo] Sold: 3 BHK, Lake Homes")).toBeTruthy();
  expect(
    screen.getByText(/not verified/, { selector: "caption" }),
  ).toBeTruthy();
  expect(screen.getByText(/half sold within 49 days/)).toBeTruthy();
  expect(screen.getByText(/12%, 69%, 93%/)).toBeTruthy();
  expect(screen.getByText(/not sale prices and not used above/)).toBeTruthy();
  expect(screen.getByText(/seed 42/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Estimate again" })).toBeTruthy();
});

test("insufficient data shows the reason and no number", async () => {
  const insufficient = valuation({
    status: "insufficient_data",
    result: {
      ...valuation().result,
      reason:
        "Insufficient data: 1 comparable sale found, at least 3 needed. No estimate is shown.",
      estimate: null,
      asking: null,
      simulation: {
        available: false,
        reason:
          "Needs at least 5 comparable sales with listed and closed dates; found 1.",
        runs: 2000,
        seed: 1,
        samples: 1,
      },
    },
  });
  const calls = stub([], insufficient);
  render(<ListingValuation listingId="l1" />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Estimate value" }),
  );
  expect((await screen.findByRole("status")).textContent).toContain(
    "Insufficient data",
  );
  expect(screen.queryByText(/Estimated range/)).toBeNull();
  expect(screen.getByText(/Not available\. Needs at least 5/)).toBeTruthy();
  expect(calls).toContain("POST /api/v1/listings/l1/valuations");
});

test("a later sale is shown against the estimate", async () => {
  stub(
    [
      valuation({
        outcome: {
          price: money("24000000.00"),
          at: "2026-11-20T00:00:00Z",
          error_pct: 0.0417,
          within_range: true,
        },
      }),
    ],
    null,
  );
  render(<ListingValuation listingId="l1" />);
  expect(
    await screen.findByText(/middle was 4% above it, inside the range/),
  ).toBeTruthy();
});
