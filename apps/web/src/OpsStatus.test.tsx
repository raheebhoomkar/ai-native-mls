import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { OpsStatus } from "./OpsStatus";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const HEALTHY = {
  checked_at: "2026-11-17T10:00:00Z",
  jobs: {
    queued: 0,
    overdue: 0,
    running: 0,
    failed_recently: 0,
    failed_platform: 0,
    unknown_kinds: [],
  },
  webhook_deliveries: { pending: 0, failed_recently: 0 },
  ai: { failed_recently: 0, last_error: null },
  alerts: [],
};

test("shows alerts, the numbers, and checks again", async () => {
  const answers = [
    {
      ...HEALTHY,
      jobs: { ...HEALTHY.jobs, queued: 3, overdue: 3 },
      alerts: ["Background jobs waiting over 5 minutes: 3."],
    },
    HEALTHY,
  ];
  const fetch = vi.fn(async () => Response.json(answers.shift()));
  vi.stubGlobal("fetch", fetch);
  render(<OpsStatus />);

  const alerts = await screen.findByRole("list", { name: "Needs attention" });
  expect(alerts.textContent).toContain("waiting over 5 minutes");
  expect(screen.getByText(/3 queued \(3 overdue\)/)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Check again" }));
  expect(await screen.findByText("No problems found.")).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("says when the status cannot be loaded", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json(
        {
          error: {
            code: "forbidden",
            message: "Platform administrators only.",
          },
        },
        { status: 403 },
      ),
    ),
  );
  render(<OpsStatus />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Could not load service health",
  );
});
