import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { POLL_MS } from "./ListingMedia";
import { ListingSuggestions } from "./ListingSuggestions";

const MEDIA = {
  id: "m1",
  listing_id: "l1",
  filename: "kitchen.jpg",
  content_type: "image/jpeg",
  size_bytes: 1000,
  sha256: "0".repeat(64),
  status: "ready",
  error: null,
  created_at: "2026-11-17T10:00:00Z",
  url: "/api/v1/media/m1/content",
  thumbnail_url: "/api/v1/media/t1/content",
  can_delete: true,
};

const RUN = {
  id: "r1",
  listing_id: "l1",
  status: "succeeded",
  agent: "vision_extraction",
  agent_version: "1",
  provider: "demo",
  model: "demo",
  model_version: "1",
  inputs: [],
  output: {
    photos: [
      {
        media_asset_id: "m1",
        features: [
          {
            attribute: "flooring",
            value: "hardwood",
            confidence: 0.9,
            evidence: "Wood planks.",
            uncertain: false,
          },
          {
            attribute: "appliance",
            value: "oven",
            confidence: 0.4,
            evidence: "Box under the hob.",
            uncertain: true,
          },
        ],
      },
    ],
  },
  error: null,
  created_at: "2026-11-17T10:00:00Z",
  started_at: null,
  finished_at: null,
  is_demo: true,
  decisions: {},
  can_review: true,
};

type Call = { key: string; body: unknown };

/** Each "METHOD /path" maps to a queue of responses; the last one repeats. */
function stubFetch(routes: Record<string, unknown[]>) {
  const calls: Call[] = [];
  const all: Record<string, unknown[]> = {
    "GET /listings/l1/media": [[MEDIA]],
    "GET /listings/l1/features": [[]],
    ...routes,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      calls.push({
        key,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      const queue = all[key];
      if (!queue) throw new Error(`Unexpected request: ${key}`);
      const next = queue.length > 1 ? queue.shift() : queue[0];
      return next instanceof Response ? next.clone() : Response.json(next);
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("starts an analysis and checks again until it finishes", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const queued = { ...RUN, status: "queued", output: null };
  const calls = stubFetch({
    "GET /listings/l1/ai/extractions": [[], [queued], [RUN]],
    "POST /listings/l1/ai/extractions": [queued],
  });
  render(<ListingSuggestions listingId="l1" canRequest />);

  expect(await screen.findByText("No analysis yet.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Analyse photos" }));
  expect(await screen.findByText("Waiting to analyse photos…")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Analyse/ })).toBeNull();

  await vi.advanceTimersByTimeAsync(POLL_MS);
  expect(await screen.findByText("hardwood")).toBeTruthy();
  expect(calls.map((c) => c.key)).toContain("POST /listings/l1/ai/extractions");
  expect(screen.getByAltText("kitchen.jpg")).toBeTruthy();
  expect(screen.getAllByText("Demo")).toHaveLength(2);
  expect(screen.getAllByText("Uncertain")).toHaveLength(1);
  expect(screen.getByText("40% confident")).toBeTruthy();
  expect(screen.getByText("Box under the hob.")).toBeTruthy();
});

test("keeps checking after one check fails", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const queued = { ...RUN, status: "queued", output: null };
  stubFetch({
    "GET /listings/l1/ai/extractions": [
      [queued],
      new Response("bad gateway", { status: 502 }),
      [RUN],
    ],
  });
  render(<ListingSuggestions listingId="l1" canRequest />);

  expect(await screen.findByText("Waiting to analyse photos…")).toBeTruthy();
  await vi.advanceTimersByTimeAsync(POLL_MS);
  expect(await screen.findByText(/status 502/)).toBeTruthy();
  await vi.advanceTimersByTimeAsync(POLL_MS);
  expect(await screen.findByText("hardwood")).toBeTruthy();
  expect(screen.queryByText(/status 502/)).toBeNull();
});

test("accepts, edits and rejects suggestions, then shows the decisions", async () => {
  const decided = {
    ...RUN,
    decisions: {
      "m1:0": { item_key: "m1:0", decision: "edited", final_value: "Teak" },
      "m1:1": { item_key: "m1:1", decision: "rejected", final_value: null },
    },
  };
  const calls = stubFetch({
    "GET /listings/l1/ai/extractions": [[RUN], [RUN], [RUN], [decided]],
    "POST /ai/runs/r1/decisions": [{}],
    "GET /listings/l1/features": [
      [],
      [],
      [],
      [{ id: "f1", attribute: "flooring", value: "Teak" }],
    ],
  });
  render(<ListingSuggestions listingId="l1" canRequest />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Accept Appliance: oven" }),
  );
  await waitFor(() =>
    expect(calls.filter((c) => c.key.startsWith("POST"))).toHaveLength(1),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Reject Appliance: oven" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit Flooring: hardwood" }),
  );
  const form = screen.getByRole("form", { name: "Edit Flooring: hardwood" });
  fireEvent.change(within(form).getByLabelText("Value"), {
    target: { value: "Teak" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));

  expect(await screen.findByText(/Edited to “Teak”/)).toBeTruthy();
  expect(screen.getByText("Rejected")).toBeTruthy();
  expect(screen.getByText("Flooring: Teak")).toBeTruthy();
  expect(
    calls
      .filter((c) => c.key === "POST /ai/runs/r1/decisions")
      .map((c) => c.body),
  ).toEqual([
    { item_key: "m1:1", decision: "accepted" },
    { item_key: "m1:1", decision: "rejected" },
    { item_key: "m1:0", decision: "edited", value: "Teak" },
  ]);
});

test("read-only users see suggestions without buttons", async () => {
  stubFetch({
    "GET /listings/l1/ai/extractions": [[{ ...RUN, can_review: false }]],
  });
  render(<ListingSuggestions listingId="l1" canRequest={false} />);

  expect(await screen.findByText("hardwood")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

test("a failed run shows the error and can be retried", async () => {
  const calls = stubFetch({
    "GET /listings/l1/ai/extractions": [
      [{ ...RUN, status: "failed", output: null, error: "Timeout: slow" }],
    ],
    "POST /listings/l1/ai/extractions": [
      Response.json(
        { error: { code: "no_photos", message: "Add a photo first." } },
        { status: 409 },
      ),
    ],
  });
  render(<ListingSuggestions listingId="l1" canRequest />);

  expect(await screen.findByText(/The analysis failed: Timeout/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Add a photo first.")).toBeTruthy();
  expect(calls.map((c) => c.key)).toContain("POST /listings/l1/ai/extractions");
});
