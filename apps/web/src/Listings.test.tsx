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
  window.location.hash = "#/listings";
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

const organisation = (permissions: string[]) => ({
  id: "o1",
  name: "Acme Realty",
  kind: "brokerage",
  my_role: "agent",
  my_permissions: permissions,
  assignable_roles: [],
});

const listing = (id: string, title: string, amount: string) => ({
  id,
  title,
  status: "pending_review",
  listing_type: "sale",
  list_price: { amount, currency: "INR" },
  organisation_name: "Acme Realty",
  listing_agent: { user_id: "u1", full_name: "Asha Agent" },
  property: {
    bedrooms: 3,
    address: { line1: "1 Road", locality: "Powai", city: "Mumbai" },
  },
});

/** Stub fetch; listing searches are answered by `search(queryString)`. */
function stubApi(
  permissions: string[],
  search: (query: URLSearchParams) => unknown,
) {
  const searches: URLSearchParams[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const [path, query = ""] = url.split("?");
      if (path === "/api/v1/auth/me") return Response.json(ME);
      if (path === "/api/v1/organisations/current")
        return Response.json(organisation(permissions));
      if (path === "/api/v1/listings") {
        const params = new URLSearchParams(query);
        searches.push(params);
        return Response.json(search(params));
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  return searches;
}

test("shows listings with formatted price, status and location", async () => {
  stubApi(["listing:read"], () => ({
    items: [listing("l1", "Lake-view apartment", "25000000.00")],
    next_cursor: null,
  }));
  render(<App />);

  const row = (await screen.findByText("Lake-view apartment")).closest("tr")!;
  expect(row.textContent).toContain("Pending review");
  expect(row.textContent).toContain("Powai, Mumbai");
  expect(row.textContent).toContain("Asha Agent");
  // Formatted for display in the listing's own currency, not shown as a raw string.
  expect(row.textContent).toMatch(/₹\s?2,50,00,000|₹\s?25,000,000/);
});

test("filters are sent to the API only when Search is pressed, and can be cleared", async () => {
  const searches = stubApi(["listing:read"], (query) => ({
    items: query.get("q") ? [] : [listing("l1", "Lake-view apartment", "1")],
    next_cursor: null,
  }));
  render(<App />);
  await screen.findByText("Lake-view apartment");
  expect(searches).toHaveLength(1);

  fireEvent.change(screen.getByLabelText("Search"), {
    target: { value: " villa " },
  });
  fireEvent.change(screen.getByLabelText("Status"), {
    target: { value: "active" },
  });
  fireEvent.change(screen.getByLabelText("Max price"), {
    target: { value: "5000000" },
  });
  fireEvent.change(screen.getByLabelText("Sort"), {
    target: { value: "price_asc" },
  });
  expect(searches).toHaveLength(1); // typing alone does not search

  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText("No listings match.")).toBeTruthy();
  expect(Object.fromEntries(searches[1]!)).toEqual({
    q: "villa",
    status: "active",
    scope: "all",
    max_price: "5000000",
    sort: "price_asc",
  });

  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(await screen.findByText("Lake-view apartment")).toBeTruthy();
  expect((screen.getByLabelText("Search") as HTMLInputElement).value).toBe("");
});

test("load more appends the next page using the cursor", async () => {
  const searches = stubApi(["listing:read"], (query) =>
    query.get("cursor") === "c1"
      ? { items: [listing("l2", "Second", "2")], next_cursor: null }
      : { items: [listing("l1", "First", "1")], next_cursor: "c1" },
  );
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Load more" }));

  expect(await screen.findByText("Second")).toBeTruthy();
  expect(screen.getByText("First")).toBeTruthy();
  expect(searches[1]!.get("sort")).toBe("newest"); // same filters as the first page
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull(),
  );
});

test("an API failure is shown instead of an empty table", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/auth/me") return Response.json(ME);
      if (url === "/api/v1/organisations/current")
        return Response.json(organisation(["listing:read"]));
      return Response.json(
        {
          error: {
            code: "internal_error",
            message: "An unexpected error occurred.",
          },
        },
        { status: 500 },
      );
    }),
  );
  render(<App />);

  expect(
    await screen.findByText(/An unexpected error occurred\./),
  ).toBeTruthy();
  expect(screen.queryByText("No listings match.")).toBeNull();
});

test("without listing:read there is no Listings link and the page is refused", async () => {
  const searches = stubApi([], () => ({ items: [], next_cursor: null }));
  render(<App />);

  expect(
    await screen.findByText("You cannot view listings in this organisation."),
  ).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Listings" })).toBeNull();
  expect(searches).toHaveLength(0);
});

// MapLibre needs WebGL; this stand-in reports a fixed visible area.
vi.mock("./MapView", () => ({
  MapView: ({
    points,
    onSearchArea,
  }: {
    points: unknown[];
    onSearchArea?: (bounds: Record<string, number>) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onSearchArea?.({
          min_lat: 18,
          min_lon: 72.5,
          max_lat: 19.5,
          max_lon: 73.5,
        })
      }
    >
      Search this area ({points.length} on map)
    </button>
  ),
}));

test("the map searches the visible area until any area is chosen", async () => {
  const located = {
    ...listing("l1", "Lake-view apartment", "25000000.00"),
    property: {
      ...listing("l1", "", "1").property,
      location: { latitude: "19.0760000", longitude: "72.8777000" },
    },
  };
  const searches = stubApi(["listing:read"], () => ({
    items: [located, listing("l2", "Plot", "100.00")],
    next_cursor: null,
  }));
  render(<App />);
  await screen.findByText("Lake-view apartment");

  fireEvent.click(screen.getByRole("button", { name: "Show map" }));
  expect(
    screen.getByText(
      "1 of the listings below have no location and are not on the map.",
    ),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: /Search this area \(1 on map\)/ }),
  );
  await waitFor(() =>
    expect(searches.at(-1)?.get("min_lat")).toBe("18.000000"),
  );
  expect(searches.at(-1)?.get("max_lon")).toBe("73.500000");

  fireEvent.click(await screen.findByRole("button", { name: "Any area" }));
  await waitFor(() => expect(searches.at(-1)?.has("min_lat")).toBe(false));
});
