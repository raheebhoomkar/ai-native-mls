import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { setActiveOrganisation } from "./api";
import { ListingMedia, POLL_MS } from "./ListingMedia";

const ITEM = {
  id: "m1",
  listing_id: "l1",
  filename: "front.jpg",
  content_type: "image/jpeg",
  size_bytes: 1000,
  sha256: "0".repeat(64),
  status: "ready",
  error: null,
  created_at: "2026-11-17T10:00:00Z",
  url: "/api/v1/media/m1/content?expires=1&signature=a",
  thumbnail_url: "/api/v1/media/t1/content?expires=1&signature=b",
  can_delete: true,
};

/** Each "METHOD /path" maps to a queue of responses; the last one repeats. */
function stubFetch(routes: Record<string, unknown[]>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
      calls.push(key);
      const queue = routes[key];
      if (!queue) throw new Error(`Unexpected request: ${key}`);
      const next = queue.length > 1 ? queue.shift() : queue[0];
      return next instanceof Response ? next.clone() : Response.json(next);
    }),
  );
  return calls;
}

class FakeXHR {
  static sent: FakeXHR[] = [];
  url = "";
  headers: Record<string, string> = {};
  body: unknown;
  status = 0;
  responseText = "";
  upload: { onprogress?: (e: Partial<ProgressEvent>) => void } = {};
  onload?: () => void;
  onerror?: () => void;
  open(_method: string, url: string) {
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  getResponseHeader() {
    return null;
  }
  send(body: unknown) {
    this.body = body;
    FakeXHR.sent.push(this);
  }
  respond(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    act(() => this.onload?.());
  }
}

beforeEach(() => {
  FakeXHR.sent = [];
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  setActiveOrganisation("o1");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setActiveOrganisation(null);
});

const photo = new File(["x"], "garden.png", { type: "image/png" });
const choose = (file: File) =>
  fireEvent.change(screen.getByLabelText(/Add photos/), {
    target: { files: [file] },
  });

test("shows thumbnails, processing and failed photos, and retries processing", async () => {
  const calls = stubFetch({
    "GET /listings/l1/media": [
      [
        ITEM,
        {
          ...ITEM,
          id: "m2",
          filename: "hall.png",
          status: "processing",
          thumbnail_url: null,
        },
        {
          ...ITEM,
          id: "m3",
          filename: "broken.png",
          status: "failed",
          error: "The image could not be read. Upload a different file.",
          thumbnail_url: null,
        },
      ],
    ],
    "POST /media/m3/retry": [{ ...ITEM, id: "m3", status: "processing" }],
  });
  render(<ListingMedia listingId="l1" canManage />);

  const image = await screen.findByAltText("front.jpg");
  expect(image.getAttribute("src")).toBe(ITEM.thumbnail_url);
  expect(image.closest("a")?.getAttribute("href")).toBe(ITEM.url);
  expect(screen.getByText("Processing…")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toMatch(/could not be read/);

  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(calls).toContain("POST /media/m3/retry"));
});

test("checks again while a photo is processing and shows its thumbnail when ready", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const calls = stubFetch({
    "GET /listings/l1/media": [
      [{ ...ITEM, status: "processing", thumbnail_url: null }],
      [ITEM],
    ],
  });
  render(<ListingMedia listingId="l1" canManage />);
  expect(await screen.findByText("Processing…")).toBeTruthy();

  await act(() => vi.advanceTimersByTimeAsync(POLL_MS));

  expect(await screen.findByAltText("front.jpg")).toBeTruthy();
  await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 2));
  expect(calls.filter((c) => c === "GET /listings/l1/media")).toHaveLength(2);
});

test("uploads a photo with a progress bar, then shows it in the gallery", async () => {
  const calls = stubFetch({ "GET /listings/l1/media": [[], [ITEM]] });
  render(<ListingMedia listingId="l1" canManage />);
  expect(await screen.findByText("No photos yet.")).toBeTruthy();

  choose(photo);
  const xhr = FakeXHR.sent[0]!;
  expect(xhr.url).toBe("/api/v1/listings/l1/media?filename=garden.png");
  expect(xhr.headers).toEqual({
    "Content-Type": "image/png",
    "X-Organisation-ID": "o1",
  });
  expect(xhr.body).toBe(photo);
  act(() =>
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 }),
  );
  const bar = screen.getByLabelText(
    "Uploading garden.png",
  ) as HTMLProgressElement;
  expect(bar.value).toBe(0.5);

  xhr.respond(201, ITEM);

  expect(await screen.findByAltText("front.jpg")).toBeTruthy();
  expect(screen.queryByLabelText("Uploading garden.png")).toBeNull();
  expect(calls.filter((c) => c === "GET /listings/l1/media")).toHaveLength(2);
});

test("a rejected upload shows the reason and can be retried or dismissed", async () => {
  stubFetch({ "GET /listings/l1/media": [[]] });
  render(<ListingMedia listingId="l1" canManage />);
  await screen.findByText("No photos yet.");

  choose(photo);
  FakeXHR.sent[0]!.respond(415, {
    error: {
      code: "unsupported_media_type",
      message: "Upload a JPEG, PNG or WebP image.",
      request_id: "r",
      details: [],
    },
  });
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Upload a JPEG, PNG or WebP image.",
  );

  fireEvent.click(screen.getByRole("button", { name: "Retry upload" }));
  expect(FakeXHR.sent).toHaveLength(2);
  expect(screen.queryByRole("alert")).toBeNull();
  FakeXHR.sent[1]!.respond(413, {
    error: {
      code: "file_too_large",
      message: "Files can be at most 10 MB.",
      request_id: "r",
      details: [],
    },
  });
  await screen.findByText("Files can be at most 10 MB.");

  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByText("garden.png")).toBeNull();
});

test("removing a photo asks for confirmation first", async () => {
  const calls = stubFetch({
    "GET /listings/l1/media": [[ITEM], []],
    "DELETE /media/m1": [new Response(null, { status: 204 })],
  });
  render(<ListingMedia listingId="l1" canManage />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Remove front.jpg" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(calls).not.toContain("DELETE /media/m1");

  fireEvent.click(screen.getByRole("button", { name: "Remove front.jpg" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));

  expect(await screen.findByText("No photos yet.")).toBeTruthy();
  expect(calls).toContain("DELETE /media/m1");
});

test("viewers without edit rights see photos but no upload or remove controls", async () => {
  stubFetch({
    "GET /listings/l1/media": [[{ ...ITEM, can_delete: false }]],
  });
  render(<ListingMedia listingId="l1" canManage={false} />);

  expect(await screen.findByAltText("front.jpg")).toBeTruthy();
  expect(screen.queryByLabelText(/Add photos/)).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});
