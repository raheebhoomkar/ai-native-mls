/** Home page: what needs attention, shown only for what the person may do. */

import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api, describeError, type CurrentOrganisation } from "./api";
import type { components } from "./api-schema";
import { STATUS_LABELS } from "./Listings";

type Summary = components["schemas"]["DashboardOut"];

const total = (counts: Record<string, number>) =>
  Object.values(counts).reduce((sum, n) => sum + n, 0);

function StatusCounts({ counts }: { counts: Record<string, number> }) {
  const rows = Object.entries(STATUS_LABELS).filter(([s]) => counts[s]);
  if (rows.length === 0) return <p>None yet.</p>;
  return (
    <dl>
      {rows.map(([status, label]) => (
        <div key={status} className="pair">
          <dt>{label}</dt>
          <dd>{counts[status]}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Dashboard({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const can = (p: string) => organisation.my_permissions.includes(p);

  useEffect(() => {
    let cancelled = false;
    api<Summary>("/dashboard")
      .then((s) => {
        if (cancelled) return;
        setSummary(s);
        setError(null);
      })
      .catch((caught) => !cancelled && setError(describeError(caught)));
    return () => {
      cancelled = true;
    };
  }, [organisation.id, reloadKey]);

  if (error)
    return (
      <section aria-labelledby="dashboard-heading">
        <h2 id="dashboard-heading">Overview</h2>
        <p role="alert">Could not load the overview: {error}</p>
        <button type="button" onClick={() => setReloadKey((k) => k + 1)}>
          Try again
        </button>
      </section>
    );
  if (!summary) return <p>Loading overview…</p>;

  const workflows = summary.workflows ?? {};
  const activeRuns =
    (workflows.queued ?? 0) +
    (workflows.running ?? 0) +
    (workflows.waiting ?? 0);

  return (
    <section aria-labelledby="dashboard-heading">
      <h2 id="dashboard-heading">Overview</h2>
      <div className="tiles">
        {summary.listings && (
          <article className="tile" aria-labelledby="tile-mine">
            <h3 id="tile-mine">My listings</h3>
            <p className="big">{total(summary.listings.mine)}</p>
            <StatusCounts counts={summary.listings.mine} />
            <p className="tile-links">
              <Link to="/listings">All listings</Link>
              {can("listing:write") && (
                <>
                  <Link to="/listings/new">New listing</Link>
                  <Link to="/listings/import">Import</Link>
                </>
              )}
            </p>
          </article>
        )}
        {summary.listings && (
          <article className="tile" aria-labelledby="tile-org">
            <h3 id="tile-org">{organisation.name} listings</h3>
            <p className="big">{total(summary.listings.organisation)}</p>
            <StatusCounts counts={summary.listings.organisation} />
          </article>
        )}
        {summary.review_queue !== null && (
          <article className="tile" aria-labelledby="tile-review">
            <h3 id="tile-review">Policy findings to review</h3>
            <p className="big">{summary.review_queue}</p>
            <p className="tile-links">
              <Link to="/compliance">Open the review queue</Link>
            </p>
          </article>
        )}
        {summary.workflows && (
          <article className="tile" aria-labelledby="tile-workflows">
            <h3 id="tile-workflows">Workflows</h3>
            <dl>
              <div className="pair">
                <dt>Running</dt>
                <dd>{activeRuns}</dd>
              </div>
              <div className="pair">
                <dt>Waiting for review</dt>
                <dd>{workflows.awaiting_review ?? 0}</dd>
              </div>
              <div className="pair">
                <dt>Failed</dt>
                <dd>{workflows.failed ?? 0}</dd>
              </div>
              {summary.failed_jobs !== null && (
                <div className="pair">
                  <dt>Failed background jobs</dt>
                  <dd>{summary.failed_jobs}</dd>
                </div>
              )}
            </dl>
            <p className="tile-links">
              <Link to="/monitor">Open the monitor</Link>
            </p>
          </article>
        )}
        <article className="tile" aria-labelledby="tile-notifications">
          <h3 id="tile-notifications">Unread notifications</h3>
          <p className="big">{summary.unread_notifications}</p>
          <p className="tile-links">
            <Link to="/notifications">Open notifications</Link>
          </p>
        </article>
        {(can("member:read") || can("audit:read")) && (
          <article className="tile" aria-labelledby="tile-admin">
            <h3 id="tile-admin">Administration</h3>
            <ul>
              {can("member:read") && (
                <li>
                  <Link to="/members">Members and invitations</Link>
                </li>
              )}
              {can("member:manage") && (
                <>
                  <li>
                    <Link to="/api-keys">API keys</Link>
                  </li>
                  <li>
                    <Link to="/webhooks">Webhooks</Link>
                  </li>
                </>
              )}
              {can("audit:read") && (
                <li>
                  <Link to="/audit">Audit log</Link>
                </li>
              )}
            </ul>
          </article>
        )}
      </div>
    </section>
  );
}
