import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import { ComplianceQueue } from "./ComplianceQueue";
import { ListingCompliance, reviewText } from "./ListingCompliance";
import { POLL_MS } from "./ListingMedia";

const REMARKS =
  "Sunny 2 BHK near the station. Jain families only. No bachelors.";

const FINDING = {
  field: "remarks",
  rule_id: "IN-HP-01",
  rule_title: "Limits who may live or buy by religion, caste or community",
  category: "religion_caste_community",
  severity: "high",
  confidence: 0.9,
  evidence: "Jain families only",
  start: 30,
  end: 48,
  explanation: "The remarks limit who may rent or buy by religion.",
  suggestion: "Remove the restriction.",
  source: "rule",
};

const OPEN = {
  state: "open",
  decision: null,
  appeal: null,
  appeal_decision: null,
};

const DECISION = {
  decision: "accepted",
  note: null,
  decided_by_user_id: "u2",
  decided_by_name: "Broker A",
  decided_at: "2026-11-17T11:00:00Z",
};

const SCAN = {
  id: "s1",
  listing_id: "l1",
  status: "succeeded",
  listing_version: 2,
  checked_title: "Lake-view apartment",
  checked_remarks: REMARKS,
  provider: "demo",
  model: "none",
  model_version: null,
  output: {
    policy_id: "in-house-illustrative",
    policy_version: "2026.11-1",
    policy_name: "Illustrative listing policy (India)",
    policy_notice:
      "An example house policy for this demo. It is not legal advice.",
    jurisdiction: "IN",
    findings: [FINDING],
    model_checked: false,
    model_note:
      "No language model is configured (demo mode); only the rules ran.",
    model_dropped: 0,
  },
  error: null,
  created_at: "2026-11-17T10:00:00Z",
  started_at: null,
  finished_at: "2026-11-17T10:00:01Z",
  is_demo: true,
  reviews: [OPEN],
  review_open: true,
  can_review: true,
  can_appeal: false,
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

const SCANS = "GET /listings/l1/compliance/scans";

test("runs a check and shows each finding with its evidence", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const queued = { ...SCAN, status: "queued", output: null, reviews: [] };
  const calls = stubFetch({
    [SCANS]: [[], [queued], [SCAN]],
    "POST /listings/l1/compliance/scans": [queued],
  });
  render(<ListingCompliance listingId="l1" listingVersion={2} canRequest />);

  expect(await screen.findByText("Not checked yet.")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Check title and remarks" }),
  );
  expect(await screen.findByText("Waiting to check…")).toBeTruthy();

  await vi.advanceTimersByTimeAsync(POLL_MS);
  const list = await screen.findByRole("list", { name: "Findings" });
  expect(within(list).getByText("Jain families only").tagName).toBe("MARK");
  expect(within(list).getByText(/High severity/)).toBeTruthy();
  expect(
    within(list).getByText(/Rule IN-HP-01, Remarks, word rule, 90% confidence/),
  ).toBeTruthy();
  expect(
    within(list).getByText("Suggestion: Remove the restriction."),
  ).toBeTruthy();
  expect(within(list).getByText("Waiting for review")).toBeTruthy();
  expect(screen.getByText(/the AI check did not/)).toBeTruthy();
  expect(screen.getByText("Demo")).toBeTruthy();
  expect(screen.getByText(/It is not legal advice/)).toBeTruthy();
  expect(calls.map((c) => c.key)).toContain(
    "POST /listings/l1/compliance/scans",
  );
});

test("a reviewer decides a finding", async () => {
  const decided = {
    ...SCAN,
    reviews: [
      {
        ...OPEN,
        state: "edits_requested",
        decision: {
          ...DECISION,
          decision: "edits_requested",
          note: "Rephrase",
        },
      },
    ],
  };
  const calls = stubFetch({
    [SCANS]: [[SCAN], [decided]],
    "POST /compliance/scans/s1/findings/0/decision": [{}],
  });
  render(<ListingCompliance listingId="l1" listingVersion={2} canRequest />);

  const group = await screen.findByRole("group", { name: "Review finding 1" });
  const requestEdits = within(group).getByRole("button", {
    name: "Request edits",
  }) as HTMLButtonElement;
  expect(requestEdits.disabled).toBe(true);
  fireEvent.change(within(group).getByRole("textbox"), {
    target: { value: " Rephrase " },
  });
  fireEvent.click(within(group).getByRole("button", { name: "Request edits" }));

  expect(
    await screen.findByText("Edits requested by Broker A: Rephrase"),
  ).toBeTruthy();
  expect(screen.queryByRole("group")).toBeNull();
  expect(
    calls.filter((c) => c.key.startsWith("POST")).map((c) => c.body),
  ).toEqual([{ decision: "edits_requested", note: "Rephrase" }]);
});

test("the listing agent appeals, and the text says it waits for another reviewer", async () => {
  const accepted = {
    ...SCAN,
    can_review: false,
    can_appeal: true,
    reviews: [{ ...OPEN, state: "accepted", decision: DECISION }],
  };
  const appealed = {
    ...accepted,
    reviews: [
      {
        ...OPEN,
        state: "appealed",
        decision: DECISION,
        appeal: {
          ...DECISION,
          decision: "appealed",
          decided_by_name: "Agent A",
          note: "It is a PG",
        },
      },
    ],
  };
  const calls = stubFetch({
    [SCANS]: [[accepted], [appealed]],
    "POST /compliance/scans/s1/findings/0/appeal": [{}],
  });
  render(<ListingCompliance listingId="l1" listingVersion={2} canRequest />);

  expect(
    await screen.findByText("Confirmed as an issue by Broker A"),
  ).toBeTruthy();
  const form = screen.getByRole("form", { name: "Appeal finding 1" });
  const submit = within(form).getByRole("button", { name: "Appeal" });
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(form).getByLabelText("Why the decision is wrong"), {
    target: { value: "It is a PG" },
  });
  fireEvent.click(submit);

  expect(
    await screen.findByText(
      "Appealed by Agent A: It is a PG. Waiting for another reviewer.",
    ),
  ).toBeTruthy();
  expect(calls.find((c) => c.key.startsWith("POST"))?.body).toEqual({
    reason: "It is a PG",
  });
});

test("another reviewer rules on an appeal", async () => {
  const appealed = {
    ...SCAN,
    reviews: [
      {
        ...OPEN,
        state: "appealed",
        decision: DECISION,
        appeal: { ...DECISION, decision: "appealed" },
      },
    ],
  };
  const ruled = {
    ...SCAN,
    reviews: [
      {
        ...appealed.reviews[0],
        state: "overturned",
        appeal_decision: {
          ...DECISION,
          decision: "overturned",
          decided_by_name: "Admin A",
          note: "Fine for a PG",
        },
      },
    ],
  };
  const calls = stubFetch({
    [SCANS]: [[appealed], [ruled]],
    "POST /compliance/scans/s1/findings/0/appeal/decision": [{}],
  });
  render(<ListingCompliance listingId="l1" listingVersion={2} canRequest />);

  const group = await screen.findByRole("group", {
    name: "Rule on the appeal of finding 1",
  });
  fireEvent.change(within(group).getByLabelText("Reason for the ruling"), {
    target: { value: "Fine for a PG" },
  });
  fireEvent.click(
    within(group).getByRole("button", { name: "Overturn decision" }),
  );

  expect(
    await screen.findByText(
      "Appeal accepted by Admin A: Fine for a PG. The finding is set aside.",
    ),
  ).toBeTruthy();
  const trail = screen.getByRole("list", { name: "Review trail" });
  expect(
    within(trail)
      .getAllByRole("listitem")
      .map((li) => li.textContent?.split(",")[0]),
  ).toEqual([
    "Confirmed as an issue by Broker A",
    "Appealed by Broker A",
    "Appeal accepted by Admin A",
  ]);
  expect(calls.find((c) => c.key.startsWith("POST"))?.body).toEqual({
    decision: "overturned",
    note: "Fine for a PG",
  });
});

test("no findings is not called compliant, and an edited listing asks for a new check", async () => {
  const clean = {
    ...SCAN,
    output: {
      ...SCAN.output,
      findings: [],
      model_checked: true,
      model_note: null,
    },
    reviews: [],
    review_open: false,
    is_demo: false,
  };
  stubFetch({ [SCANS]: [[clean]] });
  render(
    <ListingCompliance listingId="l1" listingVersion={3} canRequest={false} />,
  );

  expect(
    await screen.findByText(
      "No findings under Illustrative listing policy (India) 2026.11-1. This is not a legal review.",
    ),
  ).toBeTruthy();
  expect(screen.getByText(/The listing changed after this check/)).toBeTruthy();
  expect(screen.queryByText(/compliant/i)).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});

test("the queue links each waiting finding to its listing", async () => {
  stubFetch({
    "GET /compliance/queue": [
      [
        {
          scan_id: "s1",
          listing_id: "l1",
          listing_title: "Lake-view apartment",
          finding_index: 0,
          finding: FINDING,
          state: "open",
          review: OPEN,
          policy_version: "2026.11-1",
          waiting_since: "2026-11-17T10:00:01Z",
        },
      ],
    ],
  });
  render(
    <MemoryRouter>
      <ComplianceQueue
        organisation={
          {
            id: "o1",
            name: "Brokerage A",
            kind: "brokerage",
            my_role: "broker",
            my_permissions: ["listing:publish"],
          } as never
        }
      />
    </MemoryRouter>,
  );

  const link = await screen.findByRole("link", { name: "Lake-view apartment" });
  expect(link.getAttribute("href")).toBe("/listings/l1");
  expect(screen.getByText("Jain families only").tagName).toBe("MARK");
  expect(screen.getByText("Waiting for review")).toBeTruthy();
});

test("a note that ends a sentence is not given a second full stop", () => {
  const appeal = { ...DECISION, decision: "appealed", note: "It is a PG." };
  expect(
    reviewText({
      ...OPEN,
      state: "appealed",
      decision: DECISION,
      appeal,
    } as never),
  ).toBe("Appealed by Broker A: It is a PG. Waiting for another reviewer.");
});
