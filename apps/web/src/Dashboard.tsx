/** Home page: what needs attention, shown only for what the person may do. */

import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api, describeError, type CurrentOrganisation } from "./api";
import type { components } from "./api-schema";
import { type Listing, ListingCard, STATUS_LABELS } from "./Listings";
import { AiTag, Icon } from "./ui";

type Summary = components["schemas"]["DashboardOut"];
type Note = components["schemas"]["NotificationsOut"]["items"][number];

const total = (counts: Record<string, number>) =>
  Object.values(counts).reduce((sum, n) => sum + n, 0);

function StatusCounts({ counts }: { counts: Record<string, number> }) {
  const rows = Object.entries(STATUS_LABELS).filter(([s]) => counts[s]);
  if (rows.length === 0) return <p className="muted">None yet.</p>;
  return (
    <>
      {/* The share of each status as one bar; the list below carries the numbers. */}
      <div className="stack" aria-hidden="true">
        {rows.map(([status]) => (
          <span
            key={status}
            data-status={status}
            style={{ flexGrow: counts[status] }}
          />
        ))}
      </div>
      <dl>
        {rows.map(([status, label]) => (
          <div key={status} className="pair" data-status={status}>
            <dt>{label}</dt>
            <dd>{counts[status]}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

/** Plain sentences about what is waiting, built from the overview numbers. */
function attention(summary: Summary): { text: string; ai: boolean }[] {
  const items: { text: string; ai: boolean }[] = [];
  const workflows = summary.workflows ?? {};
  const plural = (n: number, one: string, many: string) =>
    `${n} ${n === 1 ? one : many}`;
  if (summary.review_queue)
    items.push({
      text: `${plural(summary.review_queue, "policy finding is", "policy findings are")} waiting for your review.`,
      ai: true,
    });
  if (workflows.awaiting_review)
    items.push({
      text: `${plural(workflows.awaiting_review, "workflow is", "workflows are")} paused for a person to review.`,
      ai: true,
    });
  if (workflows.failed)
    items.push({
      text: `${plural(workflows.failed, "workflow", "workflows")} stopped with an error.`,
      ai: true,
    });
  if (summary.failed_jobs)
    items.push({
      text: `${plural(summary.failed_jobs, "background job", "background jobs")} did not finish.`,
      ai: false,
    });
  const pending = summary.listings?.organisation.pending_review;
  if (pending)
    items.push({
      text: `${plural(pending, "listing is", "listings are")} pending review before publishing.`,
      ai: false,
    });
  return items;
}

/** Latest listings and the person's latest notifications. Optional: failures hide them. */
function useRecent(organisationId: string, canReadListings: boolean) {
  const [listings, setListings] = useState<Listing[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  useEffect(() => {
    let cancelled = false;
    if (canReadListings)
      api<{ items: Listing[] }>("/listings?limit=4")
        .then((page) => !cancelled && setListings(page.items))
        .catch(() => undefined);
    api<{ items: Note[] }>("/notifications")
      .then((page) => !cancelled && setNotes(page.items.slice(0, 5)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [organisationId, canReadListings]);
  return { listings, notes };
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
  const recent = useRecent(organisation.id, can("listing:read"));

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
  if (!summary) return <p className="loading">Loading overview…</p>;

  const workflows = summary.workflows ?? {};
  const activeRuns =
    (workflows.queued ?? 0) +
    (workflows.running ?? 0) +
    (workflows.waiting ?? 0);
  const insights = attention(summary);

  return (
    <section aria-labelledby="dashboard-heading" className="dashboard">
      <h2 id="dashboard-heading">Overview</h2>
      <div className="tiles">
        {summary.listings && (
          <article className="tile span-8" aria-labelledby="tile-org">
            <h3 id="tile-org">{organisation.name} listings</h3>
            <p className="big">{total(summary.listings.organisation)}</p>
            <StatusCounts counts={summary.listings.organisation} />
          </article>
        )}
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
        {insights.length > 0 && (
          <article
            className="tile feature span-6"
            aria-labelledby="tile-attention"
          >
            <h3 id="tile-attention">Needs your attention</h3>
            <ul className="insights">
              {insights.map((item) => (
                <li key={item.text}>
                  <span className="signal live" aria-hidden="true" />
                  <span>
                    {item.text} {item.ai && <AiTag>AI pipeline</AiTag>}
                  </span>
                </li>
              ))}
            </ul>
          </article>
        )}
        {summary.review_queue !== null && (
          <article className="tile" aria-labelledby="tile-review">
            <div className="tile-top">
              <h3 id="tile-review">Policy findings to review</h3>
              <AiTag>AI + rules</AiTag>
            </div>
            <p className="big">{summary.review_queue}</p>
            <p className="tile-links">
              <Link to="/compliance">Open the review queue</Link>
            </p>
          </article>
        )}
        {summary.workflows && (
          <article className="tile" aria-labelledby="tile-workflows">
            <div className="tile-top">
              <h3 id="tile-workflows">Workflows</h3>
              <AiTag />
            </div>
            <dl>
              <div className="pair">
                <dt>
                  <span
                    className={activeRuns ? "signal live" : "signal"}
                    aria-hidden="true"
                  />
                  Running
                </dt>
                <dd>{activeRuns}</dd>
              </div>
              <div className="pair">
                <dt>
                  <span className="signal wait" aria-hidden="true" />
                  Waiting for review
                </dt>
                <dd>{workflows.awaiting_review ?? 0}</dd>
              </div>
              <div className="pair">
                <dt>
                  <span className="signal bad" aria-hidden="true" />
                  Failed
                </dt>
                <dd>{workflows.failed ?? 0}</dd>
              </div>
              {summary.failed_jobs !== null && (
                <div className="pair">
                  <dt>
                    <span className="signal bad" aria-hidden="true" />
                    Failed background jobs
                  </dt>
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

      {recent.listings.length > 0 && (
        <section aria-labelledby="recent-heading">
          <div className="section-head">
            <h3 id="recent-heading">Latest listings</h3>
            <Link to="/listings">View all listings</Link>
          </div>
          <ul className="listing-grid">
            {recent.listings.map((listing, index) => (
              <ListingCard key={listing.id} listing={listing} index={index} />
            ))}
          </ul>
        </section>
      )}

      {recent.notes.length > 0 && (
        <section aria-labelledby="activity-heading">
          <div className="section-head">
            <h3 id="activity-heading">Recent activity</h3>
            <Link to="/notifications">All notifications</Link>
          </div>
          <ul className="activity list-card">
            {recent.notes.map((note) => (
              <li key={note.id}>
                <Icon name={note.listing_id ? "comment" : "bell"} />
                <span>
                  {note.listing_id ? (
                    <Link to={`/listings/${note.listing_id}`}>
                      {note.title}
                    </Link>
                  ) : (
                    note.title
                  )}
                  <small>
                    {new Date(note.created_at).toLocaleString("en-IN", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </small>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
