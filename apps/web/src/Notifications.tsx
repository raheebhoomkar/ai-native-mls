import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router";

import { api, describeError, useAction, type CurrentOrganisation } from "./api";
import type { components } from "./api-schema";

type Page = components["schemas"]["NotificationsOut"];

export const NOTIFICATION_POLL_MS = 30_000;

const KIND_LABELS: Record<string, string> = {
  assigned: "A listing is assigned to me",
  comment: "Someone comments on a listing I work on",
  workflow_finished: "A workflow I started finishes",
};

/** Nav link with the unread count, refreshed every 30 seconds. */
export function NotificationsLink({
  organisationId,
}: {
  organisationId: string;
}) {
  const [unread, setUnread] = useState(0);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<Page>("/notifications?unread=true")
      .then((page) => !cancelled && setUnread(page.unread))
      .catch(() => undefined);
    const timer = setTimeout(() => setTick((t) => t + 1), NOTIFICATION_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [organisationId, tick]);

  return (
    <NavLink to="/notifications">
      Notifications
      {unread > 0 && (
        <>
          {" "}
          <span className="badge" aria-label={`${unread} unread`}>
            {unread}
          </span>
        </>
      )}
    </NavLink>
  );
}

/** The signed-in person's notifications and preferences in this organisation. */
export function Notifications({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [prefs, setPrefs] = useState<Record<string, boolean> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const action = useAction();

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api<Page>("/notifications"),
      api<Record<string, boolean>>("/notifications/preferences"),
    ])
      .then(([p, pr]) => {
        if (cancelled) return;
        setPage(p);
        setPrefs(pr);
      })
      .catch((caught) => !cancelled && setError(describeError(caught)));
    return () => {
      cancelled = true;
    };
  }, [organisation.id, reloadKey]);

  function post(path: string) {
    void action.run(async () => {
      await api(path, { method: "POST" });
      setReloadKey((k) => k + 1);
    });
  }

  function toggle(kind: string, enabled: boolean) {
    void action.run(async () => {
      setPrefs(
        await api<Record<string, boolean>>("/notifications/preferences", {
          method: "PUT",
          body: { [kind]: enabled },
        }),
      );
    });
  }

  return (
    <section aria-labelledby="notifications-heading">
      <h2 id="notifications-heading">Notifications</h2>
      {error && <p role="alert">{error}</p>}
      {action.error && <p role="alert">{action.error}</p>}
      {page && (
        <p>
          {page.unread} unread.{" "}
          {page.unread > 0 && (
            <button
              type="button"
              disabled={action.busy}
              onClick={() => post("/notifications/read-all")}
            >
              Mark all as read
            </button>
          )}
        </p>
      )}
      {page?.items.length === 0 && <p>Nothing yet.</p>}
      {page && page.items.length > 0 && (
        <ul aria-label="Notifications">
          {page.items.map((n) => (
            <li key={n.id}>
              {n.read_at ? n.title : <strong>{n.title}</strong>}{" "}
              <small>{new Date(n.created_at).toLocaleString("en-IN")}</small>
              {n.body && <p>{n.body}</p>}
              <p>
                {n.listing_id && (
                  <Link to={`/listings/${n.listing_id}`}>Open listing</Link>
                )}{" "}
                {!n.read_at && (
                  <button
                    type="button"
                    disabled={action.busy}
                    onClick={() => post(`/notifications/${n.id}/read`)}
                  >
                    Mark as read
                  </button>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
      {prefs && (
        <fieldset>
          <legend>Tell me when</legend>
          {Object.entries(prefs).map(([kind, enabled]) => (
            <label key={kind}>
              <input
                type="checkbox"
                checked={enabled}
                disabled={action.busy}
                onChange={(e) => toggle(kind, e.target.checked)}
              />{" "}
              {KIND_LABELS[kind] ?? kind}
            </label>
          ))}
        </fieldset>
      )}
    </section>
  );
}
