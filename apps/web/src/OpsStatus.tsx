import { useEffect, useState } from "react";

import { api, describeError } from "./api";
import type { components } from "./api-schema";

type Status = components["schemas"]["OpsStatusOut"];

/** Platform-wide background work, webhooks and AI failures. Platform administrators only. */
export function OpsStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<Status>("/ops/status")
      .then((result) => {
        if (!cancelled) {
          setStatus(result);
          setError(null);
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(describeError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return (
    <>
      <h3 id="ops-heading">Service health</h3>
      {error && <p role="alert">Could not load service health: {error}</p>}
      {!status && !error && <p>Checking…</p>}
      {status && (
        <>
          {status.alerts.length === 0 ? (
            <p>No problems found.</p>
          ) : (
            <ul aria-label="Needs attention">
              {status.alerts.map((alert) => (
                <li key={alert}>{alert}</li>
              ))}
            </ul>
          )}
          <dl aria-labelledby="ops-heading">
            <dt>Background jobs</dt>
            <dd>
              {status.jobs.queued} queued ({status.jobs.overdue} overdue),{" "}
              {status.jobs.running} running, {status.jobs.failed_recently}{" "}
              failed in the last 24 hours
            </dd>
            <dt>Webhook deliveries</dt>
            <dd>
              {status.webhook_deliveries.pending} being tried,{" "}
              {status.webhook_deliveries.failed_recently} failed in the last 24
              hours
            </dd>
            <dt>AI extraction</dt>
            <dd>
              {status.ai.failed_recently} failed in the last 24 hours
              {status.ai.last_error && (
                <> (last error: {status.ai.last_error})</>
              )}
            </dd>
          </dl>
          <p>
            <small>
              Checked {new Date(status.checked_at).toLocaleString("en-IN")}
            </small>
          </p>
        </>
      )}
      <button type="button" onClick={() => setReloadKey((k) => k + 1)}>
        Check again
      </button>
    </>
  );
}
