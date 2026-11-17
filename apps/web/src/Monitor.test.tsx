import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import type { CurrentOrganisation } from "./api";
import { Monitor } from "./Monitor";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const run = (id: string, status: string, error: string | null = null) => ({
  id,
  listing_id: `l-${id}`,
  listing_title: `Listing ${id}`,
  workflow: "listing_intake",
  workflow_version: "2",
  status,
  trace_id: null,
  passes: 1,
  max_passes: 180,
  deadline: "2026-11-17T11:00:00Z",
  error,
  requested_by_user_id: "u1",
  created_at: "2026-11-17T10:00:00Z",
  started_at: null,
  finished_at: null,
  steps: [
    {
      name: "geocode",
      status: "succeeded",
      attempts: 0,
      output: {},
      error: null,
      started_at: null,
      finished_at: null,
    },
  ],
});

function stubFetch(routes: Record<string, unknown[]>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      calls.push(key);
      const queue = routes[key];
      if (!queue) throw new Error(`Unexpected request: ${key}`);
      const next = queue.length > 1 ? queue.shift() : queue[0];
      return Response.json(next);
    }),
  );
  return calls;
}

const org = (permissions: string[]) =>
  ({
    id: "o1",
    name: "Sunrise Realty",
    my_permissions: permissions,
  }) as unknown as CurrentOrganisation;

test("lists runs, retries a failed one and shows failed jobs to admins", async () => {
  const calls = stubFetch({
    "GET /workflows?status=failed": [[run("a", "failed", "index: down")]],
    "GET /workflows?status=active": [[]],
    "GET /jobs?status=failed": [
      [
        {
          id: "j1",
          kind: "ai.extract",
          status: "failed",
          attempts: 3,
          max_attempts: 3,
          last_error: "Gemini 503",
          trace_id: "t1",
          created_at: "2026-11-17T10:00:00Z",
          run_after: "2026-11-17T10:00:00Z",
          finished_at: null,
        },
      ],
    ],
    "POST /workflows/a/retry": [run("a", "queued")],
    "POST /jobs/j1/retry": [{}],
  });
  render(
    <MemoryRouter>
      <Monitor organisation={org(["listing:read", "audit:read"])} />
    </MemoryRouter>,
  );
  expect(await screen.findByText("No runs to show.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Show"), {
    target: { value: "failed" },
  });
  expect(await screen.findByText("Listing a")).toBeTruthy();
  expect(screen.getByText(/index: down/)).toBeTruthy();
  expect(screen.getByText(/Gemini 503/)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await vi.waitFor(() => expect(calls).toContain("POST /workflows/a/retry"));
  const retryJob = screen.getByRole<HTMLButtonElement>("button", {
    name: "Retry job",
  });
  await vi.waitFor(() => expect(retryJob.disabled).toBe(false));
  fireEvent.click(retryJob);
  await vi.waitFor(() => expect(calls).toContain("POST /jobs/j1/retry"));
});

test("agents see runs but not jobs", async () => {
  const calls = stubFetch({
    "GET /workflows?status=active": [[run("b", "awaiting_review")]],
  });
  render(
    <MemoryRouter>
      <Monitor organisation={org(["listing:read"])} />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText("Waiting for a person to review"),
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  expect(screen.queryByText("Failed background jobs")).toBeNull();
  expect(calls.some((c) => c.includes("/jobs"))).toBe(false);
});
