import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import { ImportSourceDetails, ListingImport } from "./ListingImport";

const FIELDS = [
  ["title", "Title", null, true],
  ["property_type", "Property type", "PropertyType", true],
  ["listing_type", "Listing type", null, true],
  ["list_price", "Price", "ListPrice", true],
  ["city", "City", "City", true],
].map(([name, label, reso_name, required]) => ({
  name,
  label,
  reso_name,
  required,
  accepted_headers: [label],
  help: "Help text.",
}));

const COLUMNS = [
  { header: "Headline", field: "title" },
  { header: "Price", field: "list_price" },
  { header: "Facing", field: null },
];

const BAD_PREVIEW = {
  columns: COLUMNS,
  errors: [],
  ready: false,
  rows: [
    {
      number: 2,
      external_id: null,
      values: { title: "Flat", list_price: "4500000" },
      errors: [],
    },
    {
      number: 3,
      external_id: null,
      values: { title: "Plot" },
      errors: [
        {
          field: "list_price",
          column: "Asking",
          message: '"lots" is not a price.',
        },
      ],
    },
  ],
};

const GOOD_PREVIEW = {
  ...BAD_PREVIEW,
  ready: true,
  rows: [BAD_PREVIEW.rows[0]],
};

type Call = { key: string; body: unknown };

/** Each "METHOD /path" maps to a queue of responses; the last one repeats. */
function stubFetch(routes: Record<string, unknown[]>) {
  const calls: Call[] = [];
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
      return Response.json(next);
    }),
  );
  return calls;
}

function choose(content: string) {
  fireEvent.change(screen.getByLabelText("CSV file"), {
    target: {
      files: [new File([content], "listings.csv", { type: "text/csv" })],
    },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("a file with problems is previewed but cannot be imported", async () => {
  const calls = stubFetch({
    "GET /imports/fields": [FIELDS],
    "POST /imports/preview": [BAD_PREVIEW],
  });
  render(
    <MemoryRouter>
      <ListingImport />
    </MemoryRouter>,
  );
  choose("Headline,Price\nFlat,4500000\nPlot,lots\n");

  expect(await screen.findByText(/1 of 2 rows have problems/)).toBeTruthy();
  expect(
    screen.getByText('Price (column "Asking"): "lots" is not a price.'),
  ).toBeTruthy();
  expect(screen.getByText(/Headline \(as Title\), Price/)).toBeTruthy();
  expect(
    screen.getByText("Not recognised, so not imported: Facing."),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Import/ })).toBeNull();
  expect(calls.find((c) => c.key === "POST /imports/preview")?.body).toEqual({
    filename: "listings.csv",
    content: "Headline,Price\nFlat,4500000\nPlot,lots\n",
  });
});

test("a valid file is imported and links to the new drafts", async () => {
  const calls = stubFetch({
    "GET /imports/fields": [FIELDS],
    "POST /imports/preview": [GOOD_PREVIEW],
    "POST /imports": [
      {
        id: "i1",
        filename: "listings.csv",
        created_at: "2026-11-17T10:00:00Z",
        listings: [{ row_number: 2, listing_id: "l1", title: "Flat" }],
      },
    ],
  });
  render(
    <MemoryRouter>
      <ListingImport />
    </MemoryRouter>,
  );
  choose("Headline,Price\nFlat,4500000\n");

  fireEvent.click(
    await screen.findByRole("button", { name: "Import 1 listing" }),
  );

  expect(
    await screen.findByText(/Imported 1 listing from listings.csv/),
  ).toBeTruthy();
  expect(screen.getByRole("link", { name: "Flat" }).getAttribute("href")).toBe(
    "/listings/l1",
  );
  expect(calls.map((c) => c.key)).toContain("POST /imports");
  expect(screen.getByText("Download a template").getAttribute("download")).toBe(
    "listing-import-template.csv",
  );
});

test("the listing page says which file and row a listing came from", async () => {
  stubFetch({
    "GET /listings/l1/import-source": [
      {
        import_id: "i1",
        filename: "portal.csv",
        row_number: 3,
        external_id: "P-102",
        imported_at: "2026-11-17T10:00:00Z",
        source: { "Price (INR)": "85 lakh" },
      },
    ],
    "GET /listings/l2/import-source": [null],
  });
  const { rerender } = render(
    <dl>
      <ImportSourceDetails listingId="l1" />
    </dl>,
  );
  expect(
    await screen.findByText(/portal.csv, row 3 \(Listing ID P-102\)/),
  ).toBeTruthy();
  expect(screen.getByText("Price (INR): 85 lakh")).toBeTruthy();

  rerender(
    <dl>
      <ImportSourceDetails listingId="l2" />
    </dl>,
  );
  await waitFor(() => expect(screen.queryByText("Imported from")).toBeNull());
});
