import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows operational when the health endpoint succeeds", async () => {
  const fetchMock = vi.fn(async () =>
    Response.json({ status: "ok", database: "ok" }),
  );
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(await screen.findByText("Operational")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/health");
});

test("shows the API error message and request ID when the database is down", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json(
        {
          error: {
            code: "database_unavailable",
            message: "The database is not reachable.",
          },
        },
        { status: 503, headers: { "X-Request-ID": "req-123" } },
      ),
    ),
  );

  render(<App />);

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("The database is not reachable.");
  expect(alert.textContent).toContain("req-123");
});

test("shows unreachable when the request itself fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("network down");
    }),
  );

  render(<App />);

  expect((await screen.findByRole("alert")).textContent).toContain(
    "The API is not reachable.",
  );
});
