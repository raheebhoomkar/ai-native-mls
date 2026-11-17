import { useEffect, useState } from "react";

import { api, describeError } from "./api";
import type { components } from "./api-schema";
import { POLL_MS } from "./ListingMedia";
import { AiTag } from "./ui";

type Run = components["schemas"]["WorkflowRunOut"];
type Step = components["schemas"]["StepOut"];

export const STEP_LABELS: Record<string, string> = {
  geocode: "Locate the address",
  extract: "Read the photos",
  compliance: "Policy check",
  review: "Human review",
  index: "Add to search",
  valuation: "Estimate value",
};

export const STATUS_TEXT: Record<string, string> = {
  queued: "Waiting to start",
  running: "Running",
  waiting: "Waiting for background work",
  awaiting_review: "Waiting for a person to review",
  succeeded: "Finished",
  failed: "Failed",
  cancelled: "Cancelled",
  pending: "Not started",
  skipped: "Skipped",
};

export const ACTIVE = ["queued", "running", "waiting", "awaiting_review"];

function stepNote(step: Step): string | null {
  if (step.error) return step.error;
  const reason = step.output["reason"];
  return typeof reason === "string" ? reason : null;
}

/** The listing workflow: one button runs every AI and data step in order. */
export function ListingWorkflow({
  listingId,
  canRequest,
}: {
  listingId: string;
  canRequest: boolean;
}) {
  const [run, setRun] = useState<Run | null | undefined>(undefined);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    api<Run[]>(`/listings/${listingId}/workflows`)
      .then((list) => {
        if (cancelled) return;
        setRun(list[0] ?? null);
        setLoadError(null);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [listingId, reloadKey]);

  const active = !!run && ACTIVE.includes(run.status);
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [active, reloadKey]);

  async function post(path: string) {
    setBusy(true);
    setActionError(null);
    try {
      setRun(await api<Run>(path, { method: "POST" }));
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="workflow-heading">
      <div className="panel-head">
        <h3 id="workflow-heading">Workflow</h3>
        <AiTag>AI pipeline</AiTag>
      </div>
      <p>
        <small>
          Runs every step for this listing in order: locate the address, read
          the photos, check the policy, add it to search and estimate its value.
          Suggestions and findings still wait for a person.
        </small>
      </p>
      {canRequest && (
        <p>
          <button
            type="button"
            onClick={() => post(`/listings/${listingId}/workflows`)}
            disabled={busy || active}
          >
            {active ? "Workflow running…" : "Run workflow"}
          </button>{" "}
          {run && active && (
            <button
              type="button"
              onClick={() => post(`/workflows/${run.id}/cancel`)}
              disabled={busy}
            >
              Cancel run
            </button>
          )}
          {run && ["failed", "cancelled"].includes(run.status) && (
            <button
              type="button"
              onClick={() => post(`/workflows/${run.id}/retry`)}
              disabled={busy}
            >
              Retry run
            </button>
          )}
        </p>
      )}
      {loadError && <p role="alert">{loadError}</p>}
      {actionError && <p role="alert">{actionError}</p>}
      {run === null && <p>Not run yet.</p>}
      {run && (
        <>
          <p role="status">
            {STATUS_TEXT[run.status] ?? run.status}
            {run.error ? `: ${run.error}` : "."}
          </p>
          {run.status === "awaiting_review" && (
            <p>
              Decide on the photo suggestions and the policy findings below. The
              run goes on by itself after each decision. The listing cannot be
              approved until the run has finished or is cancelled.
            </p>
          )}
          <ol aria-label="Workflow steps">
            {run.steps.map((step) => (
              <li key={step.name}>
                <strong>{STEP_LABELS[step.name] ?? step.name}</strong>:{" "}
                {STATUS_TEXT[step.status] ?? step.status}
                {step.attempts > 0 && ` (tried ${step.attempts} times)`}
                {stepNote(step) && <> — {stepNote(step)}</>}
              </li>
            ))}
          </ol>
          <p>
            <small>
              Trace ID {run.trace_id ?? "none"} · pass {run.passes} of at most{" "}
              {run.max_passes}
            </small>
          </p>
        </>
      )}
    </section>
  );
}
