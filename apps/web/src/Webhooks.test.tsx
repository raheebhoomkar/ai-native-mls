import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { CurrentOrganisation } from "./api";
import { Webhooks } from "./Webhooks";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const hook = {
  id: "h1",
  url: "https://crm.example.com/hook",
  description: "",
  event_kinds: ["listing.changed"],
  created_by_user_id: "u1",
  created_at: "2026-11-17T10:00:00Z",
  disabled_at: null,
};

const delivery = {
  id: "d1",
  subscription_id: "h1",
  event_id: "e1",
  event_kind: "listing.changed",
  status: "failed",
  attempts: 6,
  last_status_code: 500,
  last_error: "The endpoint answered HTTP 500.",
  last_response: "oops",
  next_attempt_at: null,
  created_at: "2026-11-17T10:00:00Z",
  delivered_at: null,
};

function stubFetch(routes: Record<string, unknown[]>, calls: string[]) {
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
}

const ORGANISATION = {
  id: "o1",
  name: "Sunrise Realty",
} as unknown as CurrentOrganisation;

test("adds a webhook, shows the secret once, and resends a failed delivery", async () => {
  const calls: string[] = [];
  const routes: Record<string, unknown[]> = {
    "GET /webhooks": [[], [hook]],
    "POST /webhooks": [{ ...hook, secret: "whsec_abc" }],
    "GET /webhooks/h1/deliveries": [[delivery]],
    "GET /webhooks/deliveries/failed": [[]],
    "POST /webhooks/deliveries/d1/redeliver": [
      { ...delivery, status: "pending" },
    ],
  };
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
  render(
    <Webhooks
      organisation={
        { id: "o1", name: "Sunrise Realty" } as unknown as CurrentOrganisation
      }
    />,
  );
  expect(await screen.findByText("No webhooks yet.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Endpoint URL"), {
    target: { value: hook.url },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add webhook" }));
  expect((await screen.findByTestId("new-secret")).textContent).toBe(
    "whsec_abc",
  );

  fireEvent.click(
    await screen.findByRole("button", { name: "Show deliveries" }),
  );
  expect(
    await screen.findByText("The endpoint answered HTTP 500."),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Send again" }));
  await vi.waitFor(() =>
    expect(calls).toContain("POST /webhooks/deliveries/d1/redeliver"),
  );
});

test("lists failed deliveries across webhooks and sends one again", async () => {
  const calls: string[] = [];
  stubFetch(
    {
      "GET /webhooks": [[hook]],
      "GET /webhooks/deliveries/failed": [[delivery]],
      "POST /webhooks/deliveries/d1/redeliver": [
        { ...delivery, status: "pending" },
      ],
    },
    calls,
  );
  render(<Webhooks organisation={ORGANISATION} />);
  const table = await screen.findByRole("table", {
    name: "Failed deliveries, newest first",
  });
  expect(table.textContent).toContain(hook.url);
  expect(table.textContent).toContain("The endpoint answered HTTP 500.");
  fireEvent.click(screen.getByRole("button", { name: "Send again" }));
  await vi.waitFor(() =>
    expect(calls).toContain("POST /webhooks/deliveries/d1/redeliver"),
  );
});

test("says when no delivery has failed", async () => {
  stubFetch(
    { "GET /webhooks": [[hook]], "GET /webhooks/deliveries/failed": [[]] },
    [],
  );
  render(<Webhooks organisation={ORGANISATION} />);
  expect(await screen.findByText("No failed deliveries.")).toBeTruthy();
});
