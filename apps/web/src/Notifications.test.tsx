import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import type { CurrentOrganisation } from "./api";
import { Notifications, NotificationsLink } from "./Notifications";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const note = {
  id: "n1",
  kind: "assigned",
  title: "Bala assigned you: 2 BHK in Powai",
  body: "",
  listing_id: "l1",
  created_at: "2026-11-17T10:00:00Z",
  read_at: null,
};

test("shows notifications, marks them read and changes preferences", async () => {
  const calls: { key: string; body: unknown }[] = [];
  const routes: Record<string, unknown[]> = {
    "GET /notifications": [
      { items: [note], unread: 1 },
      { items: [{ ...note, read_at: "2026-11-17T11:00:00Z" }], unread: 0 },
    ],
    "GET /notifications/preferences": [
      { assigned: true, comment: true, workflow_finished: true },
    ],
    "POST /notifications/n1/read": [204],
    "PUT /notifications/preferences": [
      { assigned: true, comment: false, workflow_finished: true },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      calls.push({
        key,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      const queue = routes[key];
      if (!queue) throw new Error(`Unexpected request: ${key}`);
      const next = queue.length > 1 ? queue.shift() : queue[0];
      return next === 204
        ? new Response(null, { status: 204 })
        : Response.json(next);
    }),
  );
  render(
    <MemoryRouter>
      <Notifications
        organisation={{ id: "o1" } as unknown as CurrentOrganisation}
      />
    </MemoryRouter>,
  );
  expect(await screen.findByText("1 unread.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open listing" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Mark as read" }));
  expect(await screen.findByText("0 unread.")).toBeTruthy();

  fireEvent.click(screen.getByLabelText(/Someone comments/));
  await vi.waitFor(() =>
    expect(
      calls.find((c) => c.key === "PUT /notifications/preferences")?.body,
    ).toEqual({ comment: false }),
  );
});

test("the nav link shows the unread count", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ items: [], unread: 3 })),
  );
  render(
    <MemoryRouter>
      <NotificationsLink organisationId="o1" />
    </MemoryRouter>,
  );
  expect(await screen.findByLabelText("3 unread")).toBeTruthy();
});
