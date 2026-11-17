import { useEffect, useState, type FormEvent } from "react";

import { api, describeError, useAction, type CurrentOrganisation } from "./api";
import type { components } from "./api-schema";

type Hook = components["schemas"]["WebhookOut"];
type Created = components["schemas"]["CreatedWebhookOut"];
type Delivery = components["schemas"]["DeliveryOut"];

const EVENTS = [
  ["listing.changed", "A listing is created or changed"],
  ["property.changed", "A property is created or changed"],
  ["workflow.finished", "A listing workflow finishes, fails or is cancelled"],
] as const;

const DELIVERY_TEXT: Record<string, string> = {
  pending: "Trying",
  succeeded: "Delivered",
  failed: "Failed",
};

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-IN") : "";

/** Webhook endpoints of the organisation, with their delivery log. Administrators only. */
export function Webhooks({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const [hooks, setHooks] = useState<Hook[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["listing.changed"]);
  const [open, setOpen] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);
  const action = useAction();

  useEffect(() => {
    let cancelled = false;
    api<Hook[]>("/webhooks")
      .then((list) => {
        if (!cancelled) setHooks(list);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [organisation.id, reloadKey]);

  function create(event: FormEvent) {
    event.preventDefault();
    void action.run(async () => {
      setCreated(
        await api<Created>("/webhooks", {
          method: "POST",
          body: { url, event_kinds: events },
        }),
      );
      setUrl("");
      reload();
    });
  }

  function post(path: string, method = "POST") {
    void action.run(async () => {
      await api(path, { method });
      reload();
    });
  }

  return (
    <section aria-labelledby="webhooks-heading">
      <h2 id="webhooks-heading">Webhooks</h2>
      <p>
        Send {organisation.name}&apos;s events to another system as they happen.
        Each request is signed with the webhook&apos;s secret; the developer
        guide in <code>docs/api</code> shows how to check it. Failed deliveries
        are tried 6 times over about 15 minutes.
      </p>

      <form onSubmit={create} aria-label="New webhook">
        <p>
          <label>
            Endpoint URL{" "}
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              placeholder="https://example.com/mls-events"
            />
          </label>
        </p>
        <fieldset>
          <legend>Events</legend>
          {EVENTS.map(([kind, label]) => (
            <label key={kind}>
              <input
                type="checkbox"
                checked={events.includes(kind)}
                onChange={(e) =>
                  setEvents((current) =>
                    e.target.checked
                      ? [...current, kind]
                      : current.filter((k) => k !== kind),
                  )
                }
              />{" "}
              {label} (<code>{kind}</code>)
            </label>
          ))}
        </fieldset>
        <button type="submit" disabled={action.busy || events.length === 0}>
          Add webhook
        </button>
      </form>

      {action.error && <p role="alert">{action.error}</p>}
      {created && (
        <div className="notice" role="status">
          <p>
            Copy the signing secret now. It is not shown again:{" "}
            <code data-testid="new-secret">{created.secret}</code>
          </p>
        </div>
      )}
      {loadError && <p role="alert">{loadError}</p>}
      {hooks?.length === 0 && <p>No webhooks yet.</p>}
      {hooks && hooks.length > 0 && (
        <ul aria-label="Webhooks">
          {hooks.map((hook) => (
            <li key={hook.id}>
              <p>
                <code>{hook.url}</code> — {hook.event_kinds.join(", ")}
                {hook.disabled_at && (
                  <> (turned off {when(hook.disabled_at)})</>
                )}
              </p>
              <p>
                <button
                  type="button"
                  onClick={() => setOpen(open === hook.id ? null : hook.id)}
                >
                  {open === hook.id ? "Hide deliveries" : "Show deliveries"}
                </button>{" "}
                {!hook.disabled_at && (
                  <>
                    <button
                      type="button"
                      disabled={action.busy}
                      onClick={() => post(`/webhooks/${hook.id}/test`)}
                    >
                      Send test
                    </button>{" "}
                    <button
                      type="button"
                      disabled={action.busy}
                      onClick={() => post(`/webhooks/${hook.id}`, "DELETE")}
                    >
                      Turn off
                    </button>
                  </>
                )}
              </p>
              {open === hook.id && (
                <Deliveries
                  hookId={hook.id}
                  reloadKey={reloadKey}
                  onRedeliver={(id) =>
                    post(`/webhooks/deliveries/${id}/redeliver`)
                  }
                  busy={action.busy}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Deliveries({
  hookId,
  reloadKey,
  onRedeliver,
  busy,
}: {
  hookId: string;
  reloadKey: number;
  onRedeliver: (id: string) => void;
  busy: boolean;
}) {
  const [list, setList] = useState<Delivery[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Delivery[]>(`/webhooks/${hookId}/deliveries`)
      .then((rows) => {
        if (!cancelled) setList(rows);
      })
      .catch((caught) => {
        if (!cancelled) setError(describeError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [hookId, reloadKey]);

  if (error) return <p role="alert">{error}</p>;
  if (!list) return <p>Loading…</p>;
  if (list.length === 0) return <p>No deliveries yet.</p>;
  return (
    <div className="table-scroll">
      <table>
        <caption>Deliveries, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Event</th>
            <th scope="col">Status</th>
            <th scope="col">Attempts</th>
            <th scope="col">Last answer</th>
            <th scope="col">Created</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {list.map((d) => (
            <tr key={d.id}>
              <td>{d.event_kind}</td>
              <td>
                {DELIVERY_TEXT[d.status] ?? d.status}
                {d.status === "pending" && d.next_attempt_at && (
                  <small> (next {when(d.next_attempt_at)})</small>
                )}
              </td>
              <td>{d.attempts}</td>
              <td>
                {d.last_error ??
                  (d.last_status_code && `HTTP ${d.last_status_code}`)}
              </td>
              <td>{when(d.created_at)}</td>
              <td>
                {d.status !== "pending" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onRedeliver(d.id)}
                  >
                    Send again
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
