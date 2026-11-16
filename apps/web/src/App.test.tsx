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
  window.location.hash = "";
  window.localStorage.clear();
  setActiveOrganisation(null);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const AGENT = {
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
const ADMIN = {
  user: { ...AGENT.user, id: "u2", full_name: "Anil Admin" },
  memberships: [
    { ...AGENT.memberships[0], role: "brokerage_admin" },
    {
      ...AGENT.memberships[0],
      organisation_id: "o2",
      organisation_name: "Beta Homes",
    },
  ],
};
const ROLES = ["brokerage_admin", "broker", "agent", "api_consumer"];
const organisation = (name: string, role: string, permissions: string[]) => ({
  id: name,
  name,
  kind: "brokerage",
  my_role: role,
  my_permissions: permissions,
  assignable_roles: ROLES,
});
const AS_AGENT = organisation("Acme Realty", "agent", ["member:read"]);
const AS_ADMIN = organisation("Acme Realty", "brokerage_admin", [
  "member:read",
  "member:manage",
]);
const MEMBERS = {
  items: [
    {
      user_id: "u2",
      email: "admin@example.com",
      full_name: "Anil Admin",
      role: "brokerage_admin",
    },
    {
      user_id: "u1",
      email: "agent@example.com",
      full_name: "Asha Agent",
      role: "agent",
    },
  ],
  next_cursor: null,
};
const EMPTY = { items: [], next_cursor: null };

function envelope(status: number, code: string, message: string) {
  return Response.json(
    { error: { code, message, request_id: "req-123", details: [] } },
    { status, headers: { "X-Request-ID": "req-123" } },
  );
}

type Call = { key: string; body: unknown; organisation: string | undefined };

/** Stub fetch with one handler per "METHOD /path"; unknown calls fail the test loudly. */
function stubApi(routes: Record<string, (call: Call) => Response>) {
  const calls: Call[] = [];
  const all: typeof routes = {
    "GET /api/v1/health": () => Response.json({ status: "ok", database: "ok" }),
    ...routes,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = {
        key: `${init?.method ?? "GET"} ${url}`,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
        organisation: (init?.headers as Record<string, string>)?.[
          "X-Organisation-ID"
        ],
      };
      calls.push(call);
      const handler = all[call.key];
      if (!handler) throw new Error(`Unexpected request: ${call.key}`);
      return handler(call);
    }),
  );
  return calls;
}

const signedOut = {
  "GET /api/v1/auth/me": () =>
    envelope(401, "unauthenticated", "Sign in to continue."),
};

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

test("visitor signs in and lands in their organisation", async () => {
  const calls = stubApi({
    ...signedOut,
    "POST /api/v1/auth/login": () => Response.json(AGENT),
    "GET /api/v1/organisations/current": () => Response.json(AS_AGENT),
  });
  render(<App />);

  await screen.findByLabelText("Email");
  type("Email", "agent@example.com");
  type("Password", "a long password");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByText(/Signed in as Asha Agent/)).toBeTruthy();
  expect(
    await screen.findByText(/Working in Acme Realty \(brokerage\) as Agent/),
  ).toBeTruthy();
  expect(calls.find((c) => c.key === "POST /api/v1/auth/login")?.body).toEqual({
    email: "agent@example.com",
    password: "a long password",
  });
  // An agent gets no platform navigation.
  expect(screen.queryByRole("link", { name: "Platform" })).toBeNull();
});

test("failed sign-in shows the API message and lets the user try again", async () => {
  stubApi({
    ...signedOut,
    "POST /api/v1/auth/login": () =>
      envelope(401, "invalid_credentials", "Invalid email or password."),
  });
  render(<App />);

  await screen.findByLabelText("Email");
  type("Email", "a@example.com");
  type("Password", "wrong");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(
    (await screen.findByText(/Invalid email or password\./)).textContent,
  ).toContain("req-123");
  expect(
    (screen.getByRole("button", { name: "Sign in" }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
});

test("session check failure offers a working retry and is not treated as signed out", async () => {
  let attempts = 0;
  stubApi({
    "GET /api/v1/auth/me": () =>
      ++attempts === 1
        ? envelope(500, "internal_error", "An unexpected error occurred.")
        : Response.json(AGENT),
    "GET /api/v1/organisations/current": () => Response.json(AS_AGENT),
  });
  render(<App />);

  await screen.findByText(
    /Could not load your session: An unexpected error occurred\./,
  );
  expect(screen.queryByLabelText("Email")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText(/Signed in as Asha Agent/)).toBeTruthy();
});

test("sign out returns to the sign-in form", async () => {
  const calls = stubApi({
    "GET /api/v1/auth/me": () => Response.json(AGENT),
    "GET /api/v1/organisations/current": () => Response.json(AS_AGENT),
    "POST /api/v1/auth/logout": () => new Response(null, { status: 204 }),
  });
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
  expect(calls.some((c) => c.key === "POST /api/v1/auth/logout")).toBe(true);
});

test("agent sees members read-only", async () => {
  window.location.hash = "#/members";
  stubApi({
    "GET /api/v1/auth/me": () => Response.json(AGENT),
    "GET /api/v1/organisations/current": () => Response.json(AS_AGENT),
    "GET /api/v1/organisations/current/members": () => Response.json(MEMBERS),
  });
  render(<App />);

  expect(await screen.findByText("Asha Agent (you)")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByText("Invite a person")).toBeNull();
});

test("administrator invites, gets a one-time link, changes a role and switches organisation", async () => {
  window.location.hash = "#/members";
  const calls = stubApi({
    "GET /api/v1/auth/me": () => Response.json(ADMIN),
    "GET /api/v1/organisations/current": (call) =>
      Response.json(
        call.organisation === "o2"
          ? organisation("Beta Homes", "agent", [])
          : AS_ADMIN,
      ),
    "GET /api/v1/organisations/current/members": () => Response.json(MEMBERS),
    "GET /api/v1/organisations/current/invitations": () => Response.json(EMPTY),
    "POST /api/v1/organisations/current/invitations": () =>
      Response.json({
        id: "i1",
        email: "new@example.com",
        role: "broker",
        token: "tok/123",
      }),
    "PATCH /api/v1/organisations/current/members/u1": () =>
      new Response(null, { status: 204 }),
  });
  render(<App />);

  await screen.findByText("Anil Admin (you)");
  // Requests act in the first organisation by default.
  expect(calls.find((c) => c.key.endsWith("/members"))?.organisation).toBe(
    "o1",
  );
  // The administrator cannot change or remove themselves.
  expect(screen.queryByLabelText("Role of Anil Admin")).toBeNull();
  expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);

  type("Email", "new@example.com");
  fireEvent.change(screen.getByLabelText("Role"), {
    target: { value: "broker" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Create invitation link" }),
  );
  const link = (await screen.findByLabelText(
    "One-time link",
  )) as HTMLInputElement;
  expect(link.value).toMatch(/#\/accept-invite\?token=tok%2F123$/);
  expect(
    calls.find(
      (c) => c.key.startsWith("POST") && c.key.endsWith("/invitations"),
    )?.body,
  ).toEqual({ email: "new@example.com", role: "broker" });

  fireEvent.change(screen.getByLabelText("Role of Asha Agent"), {
    target: { value: "broker" },
  });
  await waitFor(() =>
    expect(calls.find((c) => c.key.startsWith("PATCH"))?.body).toEqual({
      role: "broker",
    }),
  );

  // Switching organisation changes the header and drops screens the new role cannot use.
  fireEvent.change(screen.getByLabelText("Organisation"), {
    target: { value: "o2" },
  });
  expect(
    await screen.findByText("You cannot view members of this organisation."),
  ).toBeTruthy();
  expect(calls.at(-1)?.organisation).toBe("o2");
  expect(screen.queryByRole("link", { name: "Members" })).toBeNull();
});

test("invited person without an account creates one from the link", async () => {
  window.location.hash = "#/accept-invite?token=tok123";
  const calls = stubApi({
    "POST /api/v1/invitations/preview": () =>
      Response.json({
        organisation_name: "Acme Realty",
        email: "new@example.com",
        role: "agent",
        account_exists: false,
      }),
    "POST /api/v1/invitations/accept": () =>
      Response.json({
        organisation_name: "Acme Realty",
        email: "new@example.com",
      }),
  });
  render(<App />);

  expect(
    await screen.findByText("new@example.com is invited as Agent."),
  ).toBeTruthy();
  type("Your full name", "Nina New");
  type("Choose a password", "a long enough password");
  fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));

  expect(
    await screen.findByText(/You are now a member of Acme Realty/),
  ).toBeTruthy();
  expect(calls.at(-1)?.body).toEqual({
    token: "tok123",
    full_name: "Nina New",
    password: "a long enough password",
  });
  // The session is never consulted on a link page.
  expect(calls.some((c) => c.key.endsWith("/auth/me"))).toBe(false);
});

test("an invalid invitation link explains what to do", async () => {
  window.location.hash = "#/accept-invite?token=bad";
  stubApi({
    "POST /api/v1/invitations/preview": () =>
      envelope(400, "invalid_token", "This link is invalid or has expired."),
  });
  render(<App />);

  expect(
    await screen.findByText("This link is invalid or has expired."),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Accept invitation" }),
  ).toBeNull();
});

test("password reset link sets a new password", async () => {
  window.location.hash = "#/reset-password?token=r1";
  const calls = stubApi({
    "POST /api/v1/auth/password-reset": () =>
      new Response(null, { status: 204 }),
  });
  render(<App />);

  type("New password", "a long enough password");
  fireEvent.click(screen.getByRole("button", { name: "Set password" }));

  expect(await screen.findByText("Password changed")).toBeTruthy();
  expect(calls.at(-1)?.body).toEqual({
    token: "r1",
    new_password: "a long enough password",
  });
});

test("platform administrator creates an organisation and a reset link", async () => {
  window.location.hash = "#/admin";
  const root = {
    user: { ...AGENT.user, is_platform_admin: true },
    memberships: [],
  };
  const calls = stubApi({
    "GET /api/v1/auth/me": () => Response.json(root),
    "GET /api/v1/organisations?limit=100": () => Response.json(EMPTY),
    "POST /api/v1/organisations": () =>
      Response.json({ id: "o9", name: "Gamma Estates" }),
    "POST /api/v1/auth/password-reset-links": () =>
      Response.json({
        email: "agent@example.com",
        token: "r1",
        expires_in_hours: 24,
      }),
  });
  render(<App />);

  await screen.findByText("Create an organisation");
  type("Name", "Gamma Estates");
  fireEvent.click(screen.getByRole("button", { name: "Create organisation" }));
  expect(await screen.findByText(/Created Gamma Estates\./)).toBeTruthy();
  expect(
    calls.find((c) => c.key === "POST /api/v1/organisations")?.body,
  ).toEqual({
    name: "Gamma Estates",
    kind: "brokerage",
  });

  type("User's email", "agent@example.com");
  fireEvent.click(screen.getByRole("button", { name: "Create reset link" }));
  const link = (await screen.findByLabelText(
    "One-time link",
  )) as HTMLInputElement;
  expect(link.value).toMatch(/#\/reset-password\?token=r1$/);
});

test("non-administrator is sent away from the platform page", async () => {
  window.location.hash = "#/admin";
  stubApi({
    "GET /api/v1/auth/me": () => Response.json(AGENT),
    "GET /api/v1/organisations/current": () => Response.json(AS_AGENT),
  });
  render(<App />);

  expect(await screen.findByText(/Signed in as Asha Agent/)).toBeTruthy();
  expect(screen.queryByText("Platform administration")).toBeNull();
});

test("profile name change is saved and password errors are shown", async () => {
  window.location.hash = "#/profile";
  const calls = stubApi({
    "GET /api/v1/auth/me": () => Response.json(AGENT),
    "GET /api/v1/organisations/current": () => Response.json(AS_AGENT),
    "PATCH /api/v1/auth/me": () =>
      Response.json({
        ...AGENT,
        user: { ...AGENT.user, full_name: "Asha Rao" },
      }),
    "POST /api/v1/auth/password": () =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "Request validation failed.",
            request_id: "r",
            details: [
              {
                field: "current_password",
                message: "The current password is not correct.",
              },
            ],
          },
        },
        { status: 422 },
      ),
  });
  render(<App />);

  await screen.findByLabelText("Full name");
  type("Full name", "Asha Rao");
  fireEvent.click(screen.getByRole("button", { name: "Save name" }));
  expect(await screen.findByText("Name saved.")).toBeTruthy();
  expect(calls.find((c) => c.key === "PATCH /api/v1/auth/me")?.body).toEqual({
    full_name: "Asha Rao",
  });

  type("Current password", "wrong");
  type("New password", "a long enough password");
  fireEvent.click(screen.getByRole("button", { name: "Change password" }));
  expect(
    await screen.findByText(/The current password is not correct\./),
  ).toBeTruthy();
});

test("system status reports an unavailable database and an unreachable API", async () => {
  stubApi({
    ...signedOut,
    "GET /api/v1/health": () =>
      envelope(503, "database_unavailable", "The database is not reachable."),
  });
  render(<App />);
  await screen.findByText(/Unavailable: The database is not reachable\./);
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
