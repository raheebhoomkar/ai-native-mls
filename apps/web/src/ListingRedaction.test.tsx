import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { POLL_MS } from "./ListingMedia";
import { ListingRedaction } from "./ListingRedaction";

const MEDIA = {
  id: "m1",
  listing_id: "l1",
  filename: "front.jpg",
  content_type: "image/jpeg",
  size_bytes: 1000,
  sha256: "0".repeat(64),
  status: "ready",
  error: null,
  created_at: "2026-11-17T10:00:00Z",
  url: "/api/v1/media/m1/content",
  thumbnail_url: "/api/v1/media/t1/content",
  can_delete: true,
};

const RUN = {
  id: "r1",
  listing_id: "l1",
  media_asset_id: "m1",
  status: "succeeded",
  agent_version: "1",
  provider: "gemini",
  model: "gemini-test",
  model_version: null,
  output: {
    policy_version: "1",
    width: 1200,
    height: 800,
    regions: [
      {
        category: "face",
        box: [0.35, 0.19, 0.2, 0.35],
        confidence: null,
        detector: "opencv-haar-faces",
        note: null,
        uncertain: false,
      },
      {
        category: "phone_number",
        box: [0.05, 0.8, 0.3, 0.1],
        confidence: 0.45,
        detector: "gemini",
        note: "phone number on a banner",
        uncertain: true,
      },
    ],
    checked: [
      {
        detector: "opencv-haar-faces",
        version: "opencv-4.14.0",
        categories: ["face"],
      },
    ],
    unchecked: [
      {
        categories: ["licence_plate", "watermark"],
        reason: "The text check failed: down",
      },
    ],
    derivative_id: "d1",
  },
  error: null,
  created_at: "2026-11-17T10:00:00Z",
  started_at: null,
  finished_at: null,
  is_demo: false,
  redacted_url: "/api/v1/media/d1/content",
  review_status: "pending",
  decision: null,
  can_review: true,
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
      return next instanceof Response ? next.clone() : Response.json(next);
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("starts a check and polls until the preview is ready", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const queued = {
    ...RUN,
    status: "queued",
    output: null,
    review_status: null,
  };
  const calls = stubFetch({
    "GET /listings/l1/redactions": [[], [queued], [RUN]],
    "POST /media/m1/redactions": [queued],
  });
  render(<ListingRedaction listingId="l1" media={[MEDIA]} canRequest />);

  expect(await screen.findByText("Not checked yet.")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Check front.jpg for sensitive content",
    }),
  );
  expect(await screen.findByText("Waiting to check…")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();

  await vi.advanceTimersByTimeAsync(POLL_MS);
  expect(await screen.findByText("Waiting for review")).toBeTruthy();
  expect(calls.map((c) => c.key)).toContain("POST /media/m1/redactions");
  expect(screen.getByAltText("front.jpg, original")).toBeTruthy();
  expect(
    screen.getByAltText("front.jpg, redacted copy").getAttribute("src"),
  ).toBe("/api/v1/media/d1/content");
  const areas = screen.getByRole("list", { name: "Areas blurred" });
  expect(within(areas).getByText("Face")).toBeTruthy();
  expect(within(areas).getByText(/no score/)).toBeTruthy();
  expect(within(areas).getByText(/45% confident/)).toBeTruthy();
  expect(within(areas).getByText("Uncertain")).toBeTruthy();
  expect(
    screen.getByText(/Not checked: Licence plate, Watermark\. The text check/),
  ).toBeTruthy();
});

test("approves and rejects with an optional note", async () => {
  const approved = {
    ...RUN,
    review_status: "approved",
    decision: { decision: "accepted", note: "Fine" },
  };
  const calls = stubFetch({
    "GET /listings/l1/redactions": [[RUN], [approved]],
    "POST /ai/redactions/r1/decision": [{}],
  });
  render(<ListingRedaction listingId="l1" media={[MEDIA]} canRequest />);

  const group = await screen.findByRole("group", {
    name: "Review the redacted copy of front.jpg",
  });
  fireEvent.change(within(group).getByLabelText("Note (optional)"), {
    target: { value: " Fine " },
  });
  fireEvent.click(within(group).getByRole("button", { name: "Approve copy" }));

  expect(await screen.findByText("Approved: Fine")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Reject copy" })).toBeNull();
  expect(
    calls.filter((c) => c.key.startsWith("POST")).map((c) => c.body),
  ).toEqual([{ decision: "accepted", note: "Fine" }]);
});

test("reject sends no note when none is given", async () => {
  const calls = stubFetch({
    "GET /listings/l1/redactions": [[RUN]],
    "POST /ai/redactions/r1/decision": [{}],
  });
  render(<ListingRedaction listingId="l1" media={[MEDIA]} canRequest />);

  fireEvent.click(await screen.findByRole("button", { name: "Reject copy" }));

  await waitFor(() =>
    expect(calls.filter((c) => c.key.startsWith("POST"))).toHaveLength(1),
  );
  expect(calls.find((c) => c.key.startsWith("POST"))?.body).toEqual({
    decision: "rejected",
  });
});

test("nothing found still asks for a look before approving", async () => {
  stubFetch({
    "GET /listings/l1/redactions": [
      [{ ...RUN, output: { ...RUN.output, regions: [], unchecked: [] } }],
    ],
  });
  render(<ListingRedaction listingId="l1" media={[MEDIA]} canRequest />);

  expect(await screen.findByText(/Nothing was found/)).toBeTruthy();
  expect(screen.queryByRole("list", { name: "Areas blurred" })).toBeNull();
});

test("read-only users see the preview without buttons", async () => {
  stubFetch({
    "GET /listings/l1/redactions": [[{ ...RUN, can_review: false }]],
  });
  render(
    <ListingRedaction listingId="l1" media={[MEDIA]} canRequest={false} />,
  );

  expect(await screen.findByText("Waiting for review")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByLabelText("Note (optional)")).toBeNull();
});

test("a failed check shows the error and can be retried", async () => {
  const calls = stubFetch({
    "GET /listings/l1/redactions": [
      [
        {
          ...RUN,
          status: "failed",
          output: null,
          review_status: null,
          redacted_url: null,
          error: "The photo could not be read.",
        },
      ],
    ],
    "POST /media/m1/redactions": [
      Response.json(
        { error: { code: "listing_archived", message: "Archived." } },
        { status: 409 },
      ),
    ],
  });
  render(<ListingRedaction listingId="l1" media={[MEDIA]} canRequest />);

  expect(await screen.findByText(/The check failed: The photo/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Check front.jpg/ }));
  expect(await screen.findByText("Archived.")).toBeTruthy();
  expect(calls.map((c) => c.key)).toContain("POST /media/m1/redactions");
});

test("photos still processing cannot be checked yet", async () => {
  stubFetch({ "GET /listings/l1/redactions": [[]] });
  render(
    <ListingRedaction
      listingId="l1"
      media={[{ ...MEDIA, status: "processing", thumbnail_url: null }]}
      canRequest
    />,
  );

  expect(await screen.findByText(/once the photo has finished/)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
