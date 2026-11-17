import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import type { CurrentOrganisation } from "./api";
import { Audit } from "./Audit";
import { Dashboard } from "./Dashboard";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function stubFetch(routes: Record<string, unknown>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      calls.push(key);
      if (!(key in routes)) throw new Error(`Unexpected request: ${key}`);
      return Response.json(routes[key]);
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

test("an agent sees listing and workflow numbers but no admin links", async () => {
  stubFetch({
    "GET /dashboard": {
      listings: {
        organisation: { draft: 3, active: 2 },
        mine: { draft: 1, pending_review: 1 },
      },
      workflows: { running: 1, awaiting_review: 2, failed: 1 },
      review_queue: null,
      failed_jobs: null,
      unread_notifications: 4,
    },
  });
  render(
    <MemoryRouter>
      <Dashboard
        organisation={org(["listing:read", "listing:write", "member:read"])}
      />
    </MemoryRouter>,
  );

  const mine = await screen.findByRole("article", { name: "My listings" });
  expect(mine.textContent).toContain("2");
  expect(mine.textContent).toContain("Pending review1");
  expect(screen.getByRole("link", { name: "New listing" })).toBeTruthy();
  const workflows = screen.getByRole("article", { name: "Workflows" });
  expect(workflows.textContent).toContain("Waiting for review2");
  expect(workflows.textContent).not.toContain("background jobs");
  expect(screen.queryByRole("article", { name: /to review/ })).toBeNull();
  expect(screen.getByRole("link", { name: "Members and invitations" }));
  expect(screen.queryByRole("link", { name: "API keys" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Audit log" })).toBeNull();
  expect(
    screen.getByRole("article", { name: "Unread notifications" }).textContent,
  ).toContain("4");
});

test("an administrator sees the review queue, failed jobs and admin links", async () => {
  stubFetch({
    "GET /dashboard": {
      listings: { organisation: {}, mine: {} },
      workflows: {},
      review_queue: 3,
      failed_jobs: 2,
      unread_notifications: 0,
    },
  });
  render(
    <MemoryRouter>
      <Dashboard
        organisation={org([
          "listing:read",
          "listing:publish",
          "member:read",
          "member:manage",
          "audit:read",
        ])}
      />
    </MemoryRouter>,
  );

  const review = await screen.findByRole("article", {
    name: "Policy findings to review",
  });
  expect(review.textContent).toContain("3");
  expect(screen.getAllByText("None yet.")).toHaveLength(2);
  expect(
    screen.getByRole("article", { name: "Workflows" }).textContent,
  ).toContain("Failed background jobs2");
  expect(screen.getByRole("link", { name: "API keys" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Audit log" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "New listing" })).toBeNull();
});

test("a failed overview says so and can be retried", async () => {
  let fail = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      fail
        ? Response.json(
            { error: { code: "internal", message: "Database down." } },
            { status: 503 },
          )
        : Response.json({
            listings: null,
            workflows: null,
            review_queue: null,
            failed_jobs: null,
            unread_notifications: 0,
          }),
    ),
  );
  render(
    <MemoryRouter>
      <Dashboard organisation={org([])} />
    </MemoryRouter>,
  );
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Database down.",
  );
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("article", { name: "Unread notifications" });
  expect(screen.queryByRole("article", { name: "My listings" })).toBeNull();
});

test("the audit log filters by area, person and record", async () => {
  const event = {
    id: "e1",
    occurred_at: "2026-11-17T10:00:00Z",
    actor_user_id: "u1",
    actor_name: "Asha Agent",
    actor_email: "asha@example.com",
    organisation_id: "o1",
    action: "listing.created",
    target_type: "listing",
    target_id: "l1",
    request_id: null,
    detail: { title: "Lake view" },
  };
  const calls = stubFetch({
    "GET /organisations/current/members?limit=100": {
      items: [{ user_id: "u1", full_name: "Asha Agent" }],
      next_cursor: null,
    },
    "GET /audit-events?limit=50": { items: [event], next_cursor: "c1" },
    "GET /audit-events?limit=50&cursor=c1": {
      items: [{ ...event, id: "e2", actor_user_id: null, actor_name: null }],
      next_cursor: null,
    },
    "GET /audit-events?limit=50&action=listing.": {
      items: [event],
      next_cursor: null,
    },
    "GET /audit-events?limit=50&action=listing.&actor_user_id=u1": {
      items: [event],
      next_cursor: null,
    },
    "GET /audit-events?limit=50&action=listing.&actor_user_id=u1&target_id=nope":
      { items: [], next_cursor: null },
  });
  render(<Audit organisation={org(["audit:read"])} />);

  expect(await screen.findByRole("cell", { name: "Asha Agent" })).toBeTruthy();
  expect(screen.getByText("title: Lake view")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByText("The system")).toBeTruthy();

  fireEvent.change(screen.getByLabelText("Area"), {
    target: { value: "listing." },
  });
  await screen.findByRole("cell", { name: "Asha Agent" });
  fireEvent.change(await screen.findByLabelText("Person"), {
    target: { value: "u1" },
  });
  fireEvent.change(screen.getByLabelText("Record ID"), {
    target: { value: "nope" },
  });
  expect(await screen.findByText("No events match.")).toBeTruthy();
  expect(calls).toContain(
    "GET /audit-events?limit=50&action=listing.&actor_user_id=u1&target_id=nope",
  );
});
