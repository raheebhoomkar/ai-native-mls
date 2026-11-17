import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ApiKeys } from "./ApiKeys";
import type { CurrentOrganisation } from "./api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const key = (overrides: Record<string, unknown> = {}) => ({
  id: "k1",
  name: "CRM sync",
  prefix: "mls_ab12cd34",
  scopes: ["listing:read"],
  rate_limit_per_minute: 60,
  created_by_user_id: "u1",
  created_at: "2026-11-17T10:00:00Z",
  last_used_at: null,
  revoked_at: null,
  requests_last_minute: 2,
  ...overrides,
});

test("creates a key, shows it once, and revokes one", async () => {
  const calls: { key: string; body: unknown }[] = [];
  const routes: Record<string, unknown[]> = {
    "GET /api-keys": [
      [],
      [key()],
      [key({ revoked_at: "2026-11-17T11:00:00Z" })],
    ],
    "POST /api-keys": [{ ...key(), key: "mls_ab12cd34_secret" }],
    "DELETE /api-keys/k1": [null],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const k = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      calls.push({
        key: k,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      const queue = routes[k];
      if (!queue) throw new Error(`Unexpected request: ${k}`);
      const next = queue.length > 1 ? queue.shift() : queue[0];
      return next === null
        ? new Response(null, { status: 204 })
        : Response.json(next);
    }),
  );
  render(
    <ApiKeys
      organisation={
        { id: "o1", name: "Sunrise Realty" } as unknown as CurrentOrganisation
      }
    />,
  );
  expect(await screen.findByText("No keys yet.")).toBeTruthy();

  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "CRM sync" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create key" }));
  expect((await screen.findByTestId("new-key")).textContent).toBe(
    "mls_ab12cd34_secret",
  );
  expect(calls.find((c) => c.key === "POST /api-keys")?.body).toEqual({
    name: "CRM sync",
    scopes: ["listing:read"],
    rate_limit_per_minute: 60,
  });
  expect(await screen.findByText("2 of 60 this minute")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
  expect(await screen.findByText(/^Revoked/)).toBeTruthy();
});
