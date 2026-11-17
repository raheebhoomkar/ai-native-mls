import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { POLL_MS } from "./ListingMedia";
import { ListingWorkflow } from "./ListingWorkflow";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const step = (name: string, status: string, output = {}, error = null) => ({
  name,
  status,
  attempts: 0,
  output,
  error,
  started_at: null,
  finished_at: null,
});

const run = (status: string, steps: ReturnType<typeof step>[]) => ({
  id: "w1",
  listing_id: "l1",
  workflow: "listing_intake",
  workflow_version: "1",
  status,
  trace_id: "trace-1",
  passes: 1,
  max_passes: 60,
  deadline: "2026-11-17T11:00:00Z",
  error: null,
  requested_by_user_id: "u1",
  created_at: "2026-11-17T10:00:00Z",
  started_at: null,
  finished_at: null,
  steps,
});

function stubFetch(routes: Record<string, unknown[]>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      const queue = routes[key];
      if (!queue) throw new Error(`Unexpected request: ${key}`);
      const next = queue.length > 1 ? queue.shift() : queue[0];
      return Response.json(next);
    }),
  );
}

test("starts a run and follows it to the end", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const waiting = run("waiting", [
    step("geocode", "succeeded"),
    step("extract", "skipped", { reason: "Add a photo first." }),
    step("compliance", "waiting"),
  ]);
  const done = run("succeeded", [
    step("geocode", "succeeded"),
    step("extract", "skipped", { reason: "Add a photo first." }),
    step("compliance", "succeeded"),
  ]);
  stubFetch({
    "GET /listings/l1/workflows": [[], [done]],
    "POST /listings/l1/workflows": [waiting],
  });
  render(<ListingWorkflow listingId="l1" canRequest />);

  expect(await screen.findByText("Not run yet.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
  expect(await screen.findByText("Waiting for background work.")).toBeTruthy();
  expect(screen.getByText(/Add a photo first/)).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Workflow running…",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);

  await vi.advanceTimersByTimeAsync(POLL_MS);
  expect(await screen.findByText("Finished.")).toBeTruthy();
});

test("readers see the run but no button", async () => {
  stubFetch({
    "GET /listings/l1/workflows": [
      [run("failed", [step("index", "failed", {}, "index down" as never)])],
    ],
  });
  render(<ListingWorkflow listingId="l1" canRequest={false} />);
  expect((await screen.findByRole("status")).textContent).toBe("Failed.");
  expect(screen.getByText(/index down/)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
