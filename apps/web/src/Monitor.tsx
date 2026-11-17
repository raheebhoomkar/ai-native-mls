import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api, describeError, type CurrentOrganisation } from "./api";
import type { components } from "./api-schema";
import { POLL_MS } from "./ListingMedia";
import { ACTIVE, STATUS_TEXT } from "./ListingWorkflow";

type Run = components["schemas"]["WorkflowRunOut"];
type Job = components["schemas"]["JobOut"];

const FILTERS = [
  ["active", "Not finished"],
  ["awaiting_review", "Waiting for review"],
  ["failed", "Failed"],
  ["", "All"],
] as const;

const when = (iso: string) => new Date(iso).toLocaleString("en-IN");

/** Workflow runs of the organisation, with cancel and retry; failed jobs for administrators. */
export function Monitor({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const canSeeJobs = organisation.my_permissions.includes("audit:read");
  const [filter, setFilter] = useState<string>("active");
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    const query = filter ? `?status=${filter}` : "";
    Promise.all([
      api<Run[]>(`/workflows${query}`),
      canSeeJobs ? api<Job[]>("/jobs?status=failed") : Promise.resolve(null),
    ])
      .then(([runList, jobList]) => {
        if (cancelled) return;
        setRuns(runList);
        setJobs(jobList);
      })
      .catch((caught) => {
        if (!cancelled) setError(describeError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [organisation.id, filter, canSeeJobs, reloadKey]);

  const anyActive = !!runs?.some((run) => ACTIVE.includes(run.status));
  useEffect(() => {
    if (!anyActive) return;
    const timer = setTimeout(reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [anyActive, reloadKey]);

  async function act(path: string) {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: "POST" });
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setBusy(false);
    }
    reload();
  }

  return (
    <section aria-labelledby="monitor-heading">
      <h2 id="monitor-heading">Monitor</h2>
      <p>
        Workflow runs on {organisation.name}&apos;s listings, newest first. The
        page refreshes while a run is still going.
      </p>
      <p>
        <label>
          Show{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            {FILTERS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </p>
      {error && <p role="alert">{error}</p>}
      {!runs && !error && <p className="loading">Loading…</p>}
      {runs?.length === 0 && <p>No runs to show.</p>}
      {runs && runs.length > 0 && (
        <div className="table-scroll">
          <table>
            <caption>Workflow runs</caption>
            <thead>
              <tr>
                <th scope="col">Listing</th>
                <th scope="col">Status</th>
                <th scope="col">Steps done</th>
                <th scope="col">Started</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const done = run.steps.filter((s) =>
                  ["succeeded", "skipped"].includes(s.status),
                ).length;
                return (
                  <tr key={run.id}>
                    <td>
                      <Link to={`/listings/${run.listing_id}`}>
                        {run.listing_title}
                      </Link>
                    </td>
                    <td>
                      {STATUS_TEXT[run.status] ?? run.status}
                      {run.error && <small> — {run.error}</small>}
                    </td>
                    <td>
                      {done} of {run.steps.length}
                    </td>
                    <td>{when(run.created_at)}</td>
                    <td>
                      {ACTIVE.includes(run.status) && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => act(`/workflows/${run.id}/cancel`)}
                        >
                          Cancel
                        </button>
                      )}
                      {["failed", "cancelled"].includes(run.status) && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => act(`/workflows/${run.id}/retry`)}
                        >
                          Retry
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {canSeeJobs && (
        <>
          <h3>Failed background jobs</h3>
          {jobs?.length === 0 && <p>No failed jobs.</p>}
          {jobs && jobs.length > 0 && (
            <ul aria-label="Failed jobs">
              {jobs.map((job) => (
                <li key={job.id}>
                  <strong>{job.kind}</strong> failed after {job.attempts}{" "}
                  attempts: {job.last_error ?? "no error recorded"}{" "}
                  <small>
                    ({when(job.created_at)}, trace {job.trace_id ?? "none"})
                  </small>{" "}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => act(`/jobs/${job.id}/retry`)}
                  >
                    Retry job
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
