import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";
import { setActiveOrganisation } from "./api";

beforeEach(() => {
  window.localStorage.clear();
  setActiveOrganisation(null);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ME = {
  user: {
    id: "u1",
    email: "agent@example.com",
    full_name: "Asha Agent",
    is_platform_admin: false,
  },
  memberships: [
    {
      organisation_id: "o1",
      organisation_name: "Acme Realty",
      organisation_kind: "brokerage",
      role: "agent",
    },
  ],
};
const ORG = {
  id: "o1",
  name: "Acme Realty",
  kind: "brokerage",
  my_role: "agent",
  my_permissions: ["listing:read", "listing:write"],
  assignable_roles: [],
};
const PROPERTY = {
  id: "p1",
  organisation_id: "o1",
  property_type: "apartment",
  address: {
    line1: "12 Lake Road",
    line2: null,
    locality: "Powai",
    city: "Mumbai",
    state: null,
    postal_code: null,
    country: "IN",
  },
  bedrooms: 3,
  bathrooms: 2,
  area: { value: "1250.50", unit: "sqft" },
  year_built: null,
  version: 4,
};
const LISTING = {
  id: "l1",
  organisation_id: "o1",
  organisation_name: "Acme Realty",
  status: "draft",
  listing_type: "sale",
  visibility: "private",
  title: "Lake-view apartment",
  remarks: "Bright corner flat",
  list_price: { amount: "25000000.00", currency: "INR" },
  sold_price: null,
  expires_on: null,
  listed_at: null,
  closed_at: null,
  listing_agent: { user_id: "u1", full_name: "Asha Agent" },
  property: PROPERTY,
  allowed_transitions: ["pending_review", "withdrawn"],
  can_edit: true,
  version: 7,
  archived_at: null,
};
const page = (items: unknown[]) => ({ items, next_cursor: null });
const history = page([
  {
    id: "h1",
    from_status: null,
    to_status: "draft",
    reason: null,
    changed_at: "2026-11-01T10:00:00Z",
  },
]);
const error = (
  status: number,
  code: string,
  message: string,
  details: unknown[] = [],
) =>
  Response.json(
    { error: { code, message, request_id: "r", details } },
    { status },
  );

type Call = { key: string; body: any }; // eslint-disable-line @typescript-eslint/no-explicit-any

/** One handler per "METHOD /path" (query string ignored); unknown calls fail the test. */
function stubApi(routes: Record<string, (call: Call) => Response>) {
  const calls: Call[] = [];
  const all: typeof routes = {
    "GET /auth/me": () => Response.json(ME),
    "GET /organisations/current": () => Response.json(ORG),
    "GET /listings/l1/media": () => Response.json([]),
    "GET /listings/l1/ai/extractions": () => Response.json([]),
    "GET /listings/l1/features": () => Response.json([]),
    "GET /listings/l1/redactions": () => Response.json([]),
    "GET /listings/l1/import-source": () => Response.json(null),
    "GET /notifications": () => Response.json({ items: [], unread: 0 }),
    "GET /listings/l1/assignment": () => Response.json(null),
    "GET /listings/l1/comments": () => Response.json([]),
    ...routes,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace("/api/v1", "").split("?")[0];
      const call = {
        key: `${init?.method ?? "GET"} ${path}`,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      };
      calls.push(call);
      const handler = all[call.key];
      if (!handler) throw new Error(`Unexpected request: ${call.key}`);
      return handler(call);
    }),
  );
  return {
    calls,
    sent: (key: string) =>
      calls.filter((c) => c.key === key).map((c) => c.body),
  };
}

function open(hash: string) {
  window.location.hash = hash;
  render(<App />);
}
const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string) =>
  fireEvent.click(screen.getByRole("button", { name }));

test("detail shows the listing, its history, and submits it for review", async () => {
  const api = stubApi({
    "GET /listings/l1": () => Response.json(LISTING),
    "GET /listings/l1/history": () => Response.json(history),
    "POST /listings/l1/transitions": () =>
      Response.json({
        ...LISTING,
        status: "pending_review",
        version: 8,
        allowed_transitions: ["draft", "withdrawn"],
      }),
  });
  open("#/listings/l1");

  expect(await screen.findByText("Lake-view apartment")).toBeTruthy();
  expect(
    screen.getByText(/Apartment · 3 bed · 2 bath · 1250.50 sq ft/),
  ).toBeTruthy();
  expect(screen.getByText("12 Lake Road, Powai, Mumbai, IN")).toBeTruthy();
  expect(await screen.findByText(/Created as Draft/)).toBeTruthy();
  // Only the transitions the API allows are offered.
  expect(
    screen.queryByRole("button", { name: "Approve and publish" }),
  ).toBeNull();

  click("Submit for review");
  type("Reason (optional)", "Ready");
  click("Confirm");

  expect(await screen.findByText("Pending review")).toBeTruthy();
  expect(api.sent("POST /listings/l1/transitions")).toEqual([
    { to: "pending_review", version: 7, reason: "Ready", sold_price: null },
  ]);
  expect(screen.getByRole("button", { name: "Return to draft" })).toBeTruthy();
  // History is fetched again for the new version.
  await waitFor(() =>
    expect(api.sent("GET /listings/l1/history")).toHaveLength(2),
  );
});

test("marking sold asks for the price and sends it in the listing currency", async () => {
  const active = {
    ...LISTING,
    status: "active",
    allowed_transitions: ["sold"],
  };
  const api = stubApi({
    "GET /listings/l1": () => Response.json(active),
    "GET /listings/l1/history": () => Response.json(history),
    "POST /listings/l1/transitions": () =>
      Response.json({
        ...active,
        status: "sold",
        allowed_transitions: [],
        sold_price: { amount: "24000000.00", currency: "INR" },
      }),
  });
  open("#/listings/l1");

  fireEvent.click(await screen.findByRole("button", { name: "Mark as sold" }));
  type("Sold price (INR)", "24000000");
  click("Confirm");

  expect(
    await screen.findByText(/reported by the listing agent, not verified/),
  ).toBeTruthy();
  expect(api.sent("POST /listings/l1/transitions")[0]).toEqual({
    to: "sold",
    version: 7,
    reason: null,
    sold_price: { amount: "24000000", currency: "INR" },
  });
  // A sold listing offers no edit and no further status change, but can be archived.
  expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
  expect(screen.getByRole("button", { name: "Archive" })).toBeTruthy();
});

test("a version conflict offers a reload that fetches the newer listing", async () => {
  let reads = 0;
  stubApi({
    "GET /listings/l1": () =>
      Response.json(
        ++reads === 1
          ? LISTING
          : { ...LISTING, title: "Renamed by a colleague", version: 8 },
      ),
    "GET /listings/l1/history": () => Response.json(history),
    "POST /listings/l1/transitions": () =>
      error(409, "version_conflict", "Changed by someone else."),
  });
  open("#/listings/l1");

  fireEvent.click(await screen.findByRole("button", { name: "Withdraw" }));
  click("Confirm");
  click(await screen.findByText("Reload listing").then((b) => b.textContent!));

  expect(await screen.findByText("Renamed by a colleague")).toBeTruthy();
  expect(screen.queryByText(/Someone else changed this listing/)).toBeNull();
});

test("a listing shared by another organisation is read-only with no history request", async () => {
  const api = stubApi({
    "GET /listings/l1": () =>
      Response.json({
        ...LISTING,
        organisation_id: "o2",
        organisation_name: "Beta Homes",
        status: "active",
        visibility: "network",
        can_edit: false,
        allowed_transitions: [],
      }),
  });
  open("#/listings/l1");

  expect(
    await screen.findByText(
      /Shared by Beta Homes\. You can view this listing but not change it\./,
    ),
  ).toBeTruthy();
  // The only buttons left on the page are the theme toggle, the header's phone menu and Sign out.
  expect(
    screen
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label") ?? b.textContent),
  ).toEqual(["Switch to dark mode", "Menu", "Sign out"]);
  expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
  expect(screen.queryByText("Status history")).toBeNull();
  expect(api.calls.some((c) => c.key.endsWith("/history"))).toBe(false);
});

test("a listing that cannot be seen is reported as not found", async () => {
  stubApi({
    "GET /listings/nope": () => error(404, "not_found", "Listing not found."),
  });
  open("#/listings/nope");
  expect(await screen.findByText("Listing not found")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Back to listings" })).toBeTruthy();
});

test("archive needs confirmation, then returns to the table", async () => {
  const api = stubApi({
    "GET /listings/l1": () =>
      Response.json({
        ...LISTING,
        status: "withdrawn",
        allowed_transitions: ["draft"],
      }),
    "GET /listings/l1/history": () => Response.json(history),
    "DELETE /listings/l1": () => new Response(null, { status: 204 }),
    "GET /listings": () => Response.json(page([])),
  });
  open("#/listings/l1");

  fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
  expect(api.calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
  click("Confirm archive");

  expect(await screen.findByText("No listings match.")).toBeTruthy();
});

test("a live listing offers no archive button", async () => {
  stubApi({
    "GET /listings/l1": () =>
      Response.json({
        ...LISTING,
        status: "active",
        allowed_transitions: ["withdrawn"],
      }),
    "GET /listings/l1/history": () => Response.json(history),
  });
  open("#/listings/l1");
  await screen.findByRole("button", { name: "Withdraw" });
  expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
});

test("new listing with a new property creates both and opens the listing", async () => {
  let listingAttempts = 0;
  const api = stubApi({
    "GET /properties": () => Response.json(page([])),
    "POST /properties": () =>
      Response.json({ ...PROPERTY, id: "p9" }, { status: 201 }),
    "POST /listings": () =>
      ++listingAttempts === 1
        ? error(422, "validation_error", "Request validation failed.", [
            {
              field: "body.list_price.currency",
              message: "String should match pattern",
            },
          ])
        : Response.json(
            { ...LISTING, id: "l9", title: "Garden villa" },
            { status: 201 },
          ),
    "GET /listings/l9": () =>
      Response.json({ ...LISTING, id: "l9", title: "Garden villa" }),
    "GET /listings/l9/history": () => Response.json(history),
  });
  open("#/listings/new");

  await screen.findByText("New listing");
  fireEvent.change(screen.getByLabelText("Property type"), {
    target: { value: "villa" },
  });
  type("Address line 1", "4 Hill Lane");
  type("City", "Pune");
  type("Bedrooms", "4");
  type("Area", "3200.5");
  type("Title", "Garden villa");
  type("List price", "55000000");
  click("Create draft listing");

  // The API's field-level message names the field.
  expect(
    await screen.findByText(/list price currency: String should match pattern/),
  ).toBeTruthy();
  expect(screen.getByText(/The property was saved\./)).toBeTruthy();
  click("Create draft listing");

  expect(
    await screen.findByRole("heading", { name: "Garden villa" }),
  ).toBeTruthy();
  // Retrying after the listing step failed must not create a second property.
  expect(api.sent("POST /properties")).toEqual([
    {
      property_type: "villa",
      address: {
        line1: "4 Hill Lane",
        line2: null,
        locality: null,
        city: "Pune",
        state: null,
        postal_code: null,
        country: "IN",
      },
      bedrooms: 4,
      bathrooms: null,
      area: { value: "3200.5", unit: "sqft" },
      year_built: null,
    },
  ]);
  expect(api.sent("POST /listings")[1]).toEqual({
    property_id: "p9",
    title: "Garden villa",
    listing_type: "sale",
    list_price: { amount: "55000000", currency: "INR" },
    visibility: "private",
    expires_on: null,
    remarks: null,
  });
});

test("new listing can reuse an existing property", async () => {
  const api = stubApi({
    "GET /properties": () => Response.json(page([PROPERTY])),
    "POST /listings": () => Response.json(LISTING, { status: 201 }),
    "GET /listings/l1": () => Response.json(LISTING),
    "GET /listings/l1/history": () => Response.json(history),
  });
  open("#/listings/new");

  await screen.findByRole("option", { name: "12 Lake Road, Powai, Mumbai" });
  fireEvent.change(
    screen.getByLabelText("Which property is this listing for?"),
    { target: { value: "p1" } },
  );
  expect(screen.queryByLabelText("Address line 1")).toBeNull();
  type("Title", "Same flat, to let");
  fireEvent.change(screen.getByLabelText("Listing for"), {
    target: { value: "rent" },
  });
  type("List price", "85000");
  click("Create draft listing");

  await screen.findByRole("heading", { name: "Lake-view apartment" });
  expect(api.sent("POST /listings")[0]).toMatchObject({
    property_id: "p1",
    listing_type: "rent",
  });
  expect(api.calls.some((c) => c.key === "POST /properties")).toBe(false);
});

test("edit saves listing and property separately, each with its own version", async () => {
  const api = stubApi({
    "GET /listings/l1": () => Response.json(LISTING),
    "PATCH /listings/l1": (call) =>
      Response.json({
        ...LISTING,
        title: call.body.title,
        list_price: call.body.list_price,
        version: 8,
      }),
    "PUT /properties/p1": (call) =>
      Response.json({ ...PROPERTY, bedrooms: call.body.bedrooms, version: 5 }),
  });
  open("#/listings/l1/edit");

  await screen.findByDisplayValue("Lake-view apartment");
  expect((screen.getByLabelText("List price") as HTMLInputElement).value).toBe(
    "25000000.00",
  );
  type("Title", "Lake-view apartment, reduced");
  type("List price", "24500000");
  click("Save listing");
  expect(await screen.findByText("Listing saved.")).toBeTruthy();
  expect(api.sent("PATCH /listings/l1")[0]).toMatchObject({
    version: 7,
    title: "Lake-view apartment, reduced",
    list_price: { amount: "24500000", currency: "INR" },
    remarks: "Bright corner flat",
  });

  type("Bedrooms", "4");
  click("Save property");
  expect(await screen.findByText("Property saved.")).toBeTruthy();
  expect(api.sent("PUT /properties/p1")[0]).toMatchObject({
    version: 4,
    bedrooms: 4,
    area: { value: "1250.50", unit: "sqft" },
  });

  // A second listing save uses the version returned by the first.
  click("Save listing");
  await waitFor(() => expect(api.sent("PATCH /listings/l1")).toHaveLength(2));
  expect(api.sent("PATCH /listings/l1")[1].version).toBe(8);
});

test("edit conflict shows both versions and keeps typed text until the user chooses", async () => {
  let reads = 0;
  stubApi({
    "GET /listings/l1": () =>
      Response.json(
        ++reads === 1
          ? LISTING
          : { ...LISTING, title: "Their title", version: 8 },
      ),
    "PATCH /listings/l1": () =>
      error(409, "version_conflict", "Changed by someone else."),
  });
  open("#/listings/l1/edit");

  await screen.findByDisplayValue("Lake-view apartment");
  type("Title", "My title");
  click("Save listing");

  const panel = await screen.findByRole("alert", { name: "Edit conflict" });
  expect(panel.textContent).toContain("now version 8");
  const row = screen.getByRole("row", { name: /Title/ });
  expect(row.textContent).toContain("My title");
  expect(row.textContent).toContain("Their title");
  expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(
    "My title",
  );
  click("Use theirs and discard mine");
  expect(await screen.findByDisplayValue("Their title")).toBeTruthy();
  expect(screen.queryByRole("alert", { name: "Edit conflict" })).toBeNull();
});

test("edit conflict: keeping mine saves on top of their version", async () => {
  let reads = 0;
  const sent: unknown[] = [];
  stubApi({
    "GET /listings/l1": () =>
      Response.json(
        ++reads === 1
          ? LISTING
          : { ...LISTING, title: "Their title", version: 8 },
      ),
    "PATCH /listings/l1": ({ body }) => {
      sent.push(body);
      return body.version === 8
        ? Response.json({ ...LISTING, title: body.title, version: 9 })
        : error(409, "version_conflict", "Changed by someone else.");
    },
  });
  open("#/listings/l1/edit");

  await screen.findByDisplayValue("Lake-view apartment");
  type("Title", "My title");
  click("Save listing");
  await screen.findByRole("alert", { name: "Edit conflict" });
  click("Save mine over theirs");
  expect(await screen.findByText("Listing saved.")).toBeTruthy();
  expect(sent.map((b) => (b as { version: number }).version)).toEqual([
    LISTING.version,
    8,
  ]);
  expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(
    "My title",
  );
});

test("a listing the caller cannot edit shows no form", async () => {
  stubApi({
    "GET /listings/l1": () => Response.json({ ...LISTING, can_edit: false }),
  });
  open("#/listings/l1/edit");
  expect(await screen.findByText("You cannot edit this listing.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Save listing" })).toBeNull();
});

test("without listing:write there is no New listing link", async () => {
  stubApi({
    "GET /organisations/current": () =>
      Response.json({ ...ORG, my_permissions: ["listing:read"] }),
    "GET /listings": () => Response.json(page([LISTING])),
  });
  open("#/listings");
  expect(
    await screen.findByRole("link", { name: "Lake-view apartment" }),
  ).toBeTruthy();
  expect(screen.queryByRole("link", { name: "New listing" })).toBeNull();
});
