/** Audit log of the organisation, newest first, with filters. Needs `audit:read`. */

import { useState } from "react";

import { type CurrentOrganisation, useList } from "./api";
import type { components } from "./api-schema";

type Event = components["schemas"]["AuditEventOut"];
type Member = components["schemas"]["MemberOut"];

// Action prefixes the API records (see the audit.record calls in services/api). Sign-in
// and password events belong to no organisation, so they are not in this log.
const AREAS = [
  ["", "Everything"],
  ["listing.", "Listings"],
  ["property.", "Properties"],
  ["media.", "Photos"],
  ["ai.", "AI suggestions and redaction"],
  ["compliance.", "Policy checks"],
  ["workflow.", "Workflows"],
  ["valuation.", "Valuations"],
  ["comment.", "Comments"],
  ["member.", "Members"],
  ["invitation.", "Invitations"],
  ["access.", "Refused access"],
  ["api_key.", "API keys"],
  ["webhook.", "Webhooks"],
  ["job.", "Background jobs"],
] as const;

const when = (iso: string) => new Date(iso).toLocaleString("en-IN");

function details(detail: Event["detail"]) {
  const text = Object.entries(detail)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("; ");
  return text.length > 160 ? `${text.slice(0, 157)}…` : text;
}

export function Audit({ organisation }: { organisation: CurrentOrganisation }) {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [target, setTarget] = useState("");
  const members = useList<Member>(
    "/organisations/current/members?limit=100",
    organisation.id,
  );

  const query = new URLSearchParams({ limit: "50" });
  if (action) query.set("action", action);
  if (actor) query.set("actor_user_id", actor);
  if (target.trim()) query.set("target_id", target.trim());
  const events = useList<Event>(`/audit-events?${query}`, organisation.id);

  return (
    <section aria-labelledby="audit-heading">
      <h2 id="audit-heading">Audit log</h2>
      <p>
        Everything recorded in {organisation.name}, newest first. Records cannot
        be changed or deleted.
      </p>
      <div className="filters" role="search" aria-label="Filter the audit log">
        <label>
          Area
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            {AREAS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Person
          <select value={actor} onChange={(e) => setActor(e.target.value)}>
            <option value="">Anyone</option>
            {members.items.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Record ID
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="A listing or other ID"
          />
        </label>
      </div>
      {events.error && <p role="alert">{events.error}</p>}
      {events.loading ? (
        <p className="loading">Loading…</p>
      ) : events.items.length === 0 ? (
        !events.error && <p>No events match.</p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">Action</th>
                <th scope="col">Record</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {events.items.map((event) => (
                <tr key={event.id}>
                  <td>{when(event.occurred_at)}</td>
                  <td>
                    {event.actor_name ??
                      (event.actor_user_id ? "A former user" : "The system")}
                  </td>
                  <td>
                    <code>{event.action}</code>
                  </td>
                  <td>
                    {event.target_type && (
                      <>
                        {event.target_type} <small>{event.target_id}</small>
                      </>
                    )}
                  </td>
                  <td className="wrap">{details(event.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {events.next && (
        <button type="button" onClick={() => void events.loadMore()}>
          Load more
        </button>
      )}
    </section>
  );
}
