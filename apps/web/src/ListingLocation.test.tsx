import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ListingLocation } from "./ListingLocation";
import { POLL_MS } from "./ListingMedia";
import type { Listing } from "./Listings";

// MapLibre needs WebGL; the map itself is checked in the browser. This stand-in lists the points.
vi.mock("./MapView", () => ({
  MapView: ({
    points,
    onPick,
  }: {
    points: { id: string; lat: number; lon: number }[];
    onPick?: (lat: number, lon: number) => void;
  }) => (
    <div>
      <ul aria-label="map points">
        {points.map((p) => (
          <li key={p.id}>{`${p.lat},${p.lon}`}</li>
        ))}
      </ul>
      {onPick && (
        <button type="button" onClick={() => onPick(19.1, 72.9)}>
          pick on map
        </button>
      )}
    </div>
  ),
}));

type Property = Listing["property"];

const LOCATED = {
  latitude: "19.0760000",
  longitude: "72.8777000",
  source: "demo",
  precision: "city",
  located_at: "2026-11-17T10:00:00Z",
  attribution: null,
};

const property = (overrides: Partial<Property> = {}) =>
  ({
    id: "p1",
    location: LOCATED,
    location_status: "located",
    location_error: null,
    ...overrides,
  }) as Property;

const ENRICHMENT = [
  {
    key: "flood_risk",
    label: "Flood risk",
    value: null,
    source: null,
    retrieved_at: null,
    reason: "No neighbourhood data source is set up.",
  },
];

function stubApi(routes: Record<string, unknown[]>) {
  const calls: { key: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      calls.push({
        key,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      const queue = {
        "GET /properties/p1/enrichment": [ENRICHMENT],
        ...routes,
      }[key];
      if (!queue) throw new Error(`Unexpected request: ${key}`);
      return Response.json(queue.length > 1 ? queue.shift() : queue[0]);
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("shows the point, how exact it is, its source and the neighbourhood", async () => {
  stubApi({});
  render(<ListingLocation property={property()} title="Flat" isOwn canEdit />);
  expect(screen.getByText(/Accurate to the city centre only/)).toBeTruthy();
  expect(screen.getByText(/demo geocoder \(approximate centres/)).toBeTruthy();
  expect(screen.getByText("19.076,72.8777")).toBeTruthy();
  expect(
    await screen.findByText(
      "Not available: No neighbourhood data source is set up.",
    ),
  ).toBeTruthy();
});

test("polls while the address is being located", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  stubApi({ "GET /properties/p1": [property()] });
  render(
    <ListingLocation
      property={property({ location: null, location_status: "pending" })}
      title="Flat"
      isOwn
      canEdit
    />,
  );
  expect(screen.getByText("Finding this address on the map…")).toBeTruthy();
  await vi.advanceTimersByTimeAsync(POLL_MS);
  expect(
    await screen.findByText(/Accurate to the city centre only/),
  ).toBeTruthy();
});

test("not found explains itself; an editor sets the point by hand", async () => {
  const calls = stubApi({
    "PUT /properties/p1/location": [
      property({
        location: { ...LOCATED, source: "manual", precision: "address" },
      }),
    ],
  });
  render(
    <ListingLocation
      property={property({
        location: null,
        location_status: "not_found",
        location_error: "No match for this address. Set the point by hand.",
      })}
      title="Flat"
      isOwn
      canEdit
    />,
  );
  expect(screen.getByText(/No match for this address/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Set the point by hand" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "pick on map" }));
  expect((screen.getByLabelText("Latitude") as HTMLInputElement).value).toBe(
    "19.1000000",
  );
  fireEvent.click(screen.getByRole("button", { name: "Save point" }));
  await waitFor(() =>
    expect(screen.getByText(/Source: set by hand/)).toBeTruthy(),
  );
  expect(
    calls.find((c) => c.key === "PUT /properties/p1/location")?.body,
  ).toEqual({ latitude: "19.1000000", longitude: "72.9000000" });
});

test("another organisation sees the point but cannot set it", () => {
  stubApi({});
  render(
    <ListingLocation
      property={property()}
      title="Flat"
      isOwn={false}
      canEdit={false}
    />,
  );
  expect(screen.getByText(/Accurate to/)).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Set the point by hand" }),
  ).toBeNull();
  expect(screen.queryByText("Neighbourhood")).toBeNull();
});
