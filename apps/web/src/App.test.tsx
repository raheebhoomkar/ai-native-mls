import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

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

function envelope(status: number, code: string, message: string) {
  return Response.json(
    { error: { code, message, request_id: "req-123", details: [] } },
    { status, headers: { "X-Request-ID": "req-123" } },
  );
}

/** Stub fetch with one handler per "METHOD /path"; unknown calls fail the test loudly. */
function stubApi(routes: Record<string, () => Response | Promise<Response>>) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      calls.push({
        key,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      const handler = routes[key];
      if (!handler) throw new Error(`Unexpected request: ${key}`);
      return handler();
    }),
  );
  return calls;
}

const healthy = {
  "GET /api/v1/health": () => Response.json({ status: "ok", database: "ok" }),
};

test("signed-out visitor sees the form, signs in, then sees their organisations", async () => {
  const calls = stubApi({
    ...healthy,
    "GET /api/v1/auth/me": () =>
      envelope(401, "unauthenticated", "Sign in to continue."),
    "POST /api/v1/auth/login": () => Response.json(ME),
  });
  render(<App />);

  fireEvent.change(await screen.findByLabelText("Email"), {
    target: { value: "agent@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "a long password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByText(/Signed in as Asha Agent/)).toBeTruthy();
  expect(screen.getByText("Acme Realty — Agent")).toBeTruthy();
  expect(
    calls.find((call) => call.key === "POST /api/v1/auth/login")?.body,
  ).toEqual({
    email: "agent@example.com",
    password: "a long password",
  });
});

test("failed sign-in shows the API message and lets the user try again", async () => {
  stubApi({
    ...healthy,
    "GET /api/v1/auth/me": () =>
      envelope(401, "unauthenticated", "Sign in to continue."),
    "POST /api/v1/auth/login": () =>
      envelope(401, "invalid_credentials", "Invalid email or password."),
  });
  render(<App />);

  fireEvent.change(await screen.findByLabelText("Email"), {
    target: { value: "a@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "wrong" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  const alert = await screen.findByText(/Invalid email or password\./);
  expect(alert.textContent).toContain("req-123");
  const button = screen.getByRole("button", {
    name: "Sign in",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(false);
});

test("returning user with a valid session skips the form and can sign out", async () => {
  const calls = stubApi({
    ...healthy,
    "GET /api/v1/auth/me": () => Response.json(ME),
    "POST /api/v1/auth/logout": () => new Response(null, { status: 204 }),
  });
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));

  expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
  expect(calls.some((call) => call.key === "POST /api/v1/auth/logout")).toBe(
    true,
  );
});

test("session check failure is shown with a working retry, not as signed out", async () => {
  let attempts = 0;
  stubApi({
    ...healthy,
    "GET /api/v1/auth/me": () => {
      attempts += 1;
      return attempts === 1
        ? envelope(500, "internal_error", "An unexpected error occurred.")
        : Response.json(ME);
    },
  });
  render(<App />);

  expect(
    (await screen.findByText(/Could not load your session/)).textContent,
  ).toContain("An unexpected error occurred.");
  expect(screen.queryByLabelText("Email")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText(/Signed in as Asha Agent/)).toBeTruthy();
});

test("system status reports operational, API errors and an unreachable API", async () => {
  const signedOut = {
    "GET /api/v1/auth/me": () =>
      envelope(401, "unauthenticated", "Sign in to continue."),
  };

  stubApi({ ...signedOut, ...healthy });
  render(<App />);
  expect(await screen.findByText("Operational")).toBeTruthy();
  cleanup();

  stubApi({
    ...signedOut,
    "GET /api/v1/health": () =>
      envelope(503, "database_unavailable", "The database is not reachable."),
  });
  render(<App />);
  await waitFor(() =>
    expect(
      screen.getByText(/Unavailable: The database is not reachable\./),
    ).toBeTruthy(),
  );
  cleanup();

  stubApi({
    ...signedOut,
    "GET /api/v1/health": () => {
      throw new TypeError("network down");
    },
  });
  render(<App />);
  expect(
    await screen.findByText(/Unavailable: The API is not reachable\./),
  ).toBeTruthy();
});
