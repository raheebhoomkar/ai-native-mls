import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ListingCollaboration } from "./ListingCollaboration";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const comment = (overrides: Record<string, unknown> = {}) => ({
  id: "c1",
  listing_id: "l1",
  author_user_id: "u1",
  author_name: "Asha Agent",
  visibility: "team",
  body: "Price looks high.",
  created_at: "2026-11-17T10:00:00Z",
  edited_at: null,
  deleted_at: null,
  ...overrides,
});

function stub(routes: Record<string, unknown[]>) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "").split("?")[0]}`;
      calls.push({
        key,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      const queue = routes[key];
      if (!queue) throw new Error(`Unexpected request: ${key}`);
      const next = queue.length > 1 ? queue.shift() : queue[0];
      return next === null
        ? Response.json(null)
        : next === 204
          ? new Response(null, { status: 204 })
          : Response.json(next);
    }),
  );
  return calls;
}

const members = {
  items: [
    { user_id: "u2", full_name: "Bala Broker", role: "broker" },
    { user_id: "u3", full_name: "Feed Bot", role: "api_consumer" },
  ],
  next_cursor: null,
};

test("assigns a teammate, posts a private note, and shows the timeline", async () => {
  const calls = stub({
    "GET /listings/l1/assignment": [
      null,
      {
        user_id: "u2",
        user_name: "Bala Broker",
        assigned_by_user_id: "u1",
        note: null,
        assigned_at: "2026-11-17T10:00:00Z",
      },
    ],
    "GET /organisations/current/members": [members],
    "PUT /listings/l1/assignment": [{}],
    "GET /listings/l1/comments": [
      [comment()],
      [comment(), comment({ id: "c2", visibility: "private", body: "Mine" })],
    ],
    "POST /listings/l1/comments": [comment({ id: "c2" })],
    "GET /listings/l1/activity": [
      [
        {
          at: "2026-11-17T10:00:00Z",
          kind: "event",
          action: "listing.created",
          actor_name: "Asha Agent",
          summary: "created the listing",
          comment_id: null,
          visibility: null,
        },
      ],
    ],
  });
  render(
    <ListingCollaboration
      listingId="l1"
      organisationId="o1"
      myUserId="u1"
      canEdit
      canWrite
    />,
  );
  expect(await screen.findByText("Price looks high.")).toBeTruthy();
  // Read-only members cannot be assigned, so they are not offered.
  await screen.findByRole("option", { name: "Bala Broker" });
  expect(screen.queryByRole("option", { name: "Feed Bot" })).toBeNull();

  fireEvent.change(screen.getByLabelText("Assign to"), {
    target: { value: "u2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Assign" }));
  expect(
    await screen.findByText("Bala Broker", { selector: "strong" }),
  ).toBeTruthy();

  fireEvent.change(screen.getByLabelText("Comment"), {
    target: { value: "Mine" },
  });
  fireEvent.click(screen.getByLabelText(/Private note/));
  fireEvent.click(screen.getByRole("button", { name: "Save note" }));
  expect(await screen.findByText(/private note, only you/)).toBeTruthy();
  expect(
    calls.find((c) => c.key === "POST /listings/l1/comments")?.body,
  ).toEqual({
    body: "Mine",
    visibility: "private",
  });

  fireEvent.click(screen.getByRole("button", { name: "Show activity" }));
  expect(await screen.findByText(/created the listing/)).toBeTruthy();
});
