import { type FormEvent, useEffect, useState } from "react";

import { api, describeError } from "./api";
import type { components } from "./api-schema";
import { POLL_MS } from "./ListingMedia";

type Run = components["schemas"]["AgentRunOut"];
type Suggestion = components["schemas"]["Feature"];
type Decision = components["schemas"]["DecisionOut"];
type Media = components["schemas"]["MediaOut"];
type ListingFeature = components["schemas"]["ListingFeatureOut"];

type Loaded = { runs: Run[]; media: Media[]; features: ListingFeature[] };

const label = (attribute: string) =>
  (attribute.charAt(0).toUpperCase() + attribute.slice(1)).replace(/_/g, " ");

const DECISION_TEXT: Record<string, string> = {
  accepted: "Accepted",
  edited: "Edited",
  rejected: "Rejected",
};

/** AI suggestions from the listing's photos. Each one waits for a person to accept, edit or reject it. */
export function ListingSuggestions({
  listingId,
  canRequest,
}: {
  listingId: string;
  canRequest: boolean;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api<Run[]>(`/listings/${listingId}/ai/extractions`),
      api<Media[]>(`/listings/${listingId}/media`),
      api<ListingFeature[]>(`/listings/${listingId}/features`),
    ])
      .then(([runs, media, features]) => {
        if (cancelled) return;
        setLoaded({ runs, media, features });
        setLoadError(null);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [listingId, reloadKey]);

  // Newest run only; earlier runs stay in the API for the record.
  const run = loaded?.runs[0];
  const working = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!working) return;
    // Keyed on each load attempt, so a failed check (proxy reset) does not stop polling.
    const timer = setTimeout(reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [working, reloadKey]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
    reload();
  }

  const analyse = () =>
    act(() => api(`/listings/${listingId}/ai/extractions`, { method: "POST" }));

  const decide = (
    runId: string,
    body: { item_key: string; decision: string; value?: string },
  ) => act(() => api(`/ai/runs/${runId}/decisions`, { method: "POST", body }));

  const thumbnails = new Map(
    loaded?.media.map((m) => [m.id, m] as const) ?? [],
  );

  return (
    <section aria-labelledby="suggestions-heading" className="suggestions">
      <h3 id="suggestions-heading">AI suggestions</h3>
      <p>
        <small>
          Read from the photos. Nothing is added to the listing until you accept
          or edit it.
        </small>
      </p>
      {loadError && (
        <div className="notice">
          <p role="alert">{loadError}</p>
          <button type="button" onClick={reload}>
            Try again
          </button>
        </div>
      )}
      {actionError && <p role="alert">{actionError}</p>}
      {!loaded && !loadError && <p>Loading…</p>}

      {loaded && !run && <p>No analysis yet.</p>}
      {working && (
        <p role="status">
          {run.status === "queued"
            ? "Waiting to analyse photos…"
            : "Analysing photos…"}
        </p>
      )}
      {run?.status === "failed" && (
        <p role="alert">The analysis failed: {run.error}</p>
      )}
      {canRequest && loaded && !working && (
        <button type="button" disabled={busy} onClick={() => void analyse()}>
          {run?.status === "failed"
            ? "Try again"
            : run
              ? "Analyse photos again"
              : "Analyse photos"}
        </button>
      )}

      {run?.status === "succeeded" && run.output && (
        <>
          {run.output.photos.every((p) => p.features.length === 0) && (
            <p>No features were found in the photos.</p>
          )}
          <ul className="suggestion-photos">
            {run.output.photos
              .filter((p) => p.features.length > 0)
              .map((photo) => {
                const media = thumbnails.get(photo.media_asset_id);
                return (
                  <li key={photo.media_asset_id}>
                    {media?.thumbnail_url ? (
                      <img src={media.thumbnail_url} alt={media.filename} />
                    ) : (
                      <span className="caption">Photo removed</span>
                    )}
                    <ul className="suggestion-list">
                      {photo.features.map((feature, index) => {
                        const key = `${photo.media_asset_id}:${index}`;
                        return (
                          <SuggestionItem
                            key={key}
                            feature={feature}
                            isDemo={run.is_demo}
                            decision={run.decisions[key]}
                            canReview={run.can_review}
                            busy={busy}
                            onDecide={(decision, value) =>
                              void decide(run.id, {
                                item_key: key,
                                decision,
                                value,
                              })
                            }
                          />
                        );
                      })}
                    </ul>
                  </li>
                );
              })}
          </ul>
        </>
      )}

      <h3>Confirmed features</h3>
      {loaded?.features.length === 0 && <p>None yet.</p>}
      {loaded && loaded.features.length > 0 && (
        <ul>
          {loaded.features.map((f) => (
            <li key={f.id}>
              {label(f.attribute)}: {f.value}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SuggestionItem({
  feature,
  isDemo,
  decision,
  canReview,
  busy,
  onDecide,
}: {
  feature: Suggestion;
  isDemo: boolean;
  decision: Decision | undefined;
  canReview: boolean;
  busy: boolean;
  onDecide: (
    decision: "accepted" | "edited" | "rejected",
    value?: string,
  ) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(feature.value);
  const name = `${label(feature.attribute)}: ${feature.value}`;

  function save(event: FormEvent) {
    event.preventDefault();
    setEditing(false);
    onDecide("edited", value);
  }

  return (
    <li>
      <strong>{label(feature.attribute)}:</strong> {feature.value}{" "}
      <small>{Math.round(feature.confidence * 100)}% confident</small>
      {feature.uncertain && <span className="badge">Uncertain</span>}
      {isDemo && <span className="badge">Demo</span>}
      <br />
      <small>{feature.evidence}</small>
      {decision ? (
        <p className="decision">
          {DECISION_TEXT[decision.decision] ?? decision.decision}
          {decision.decision === "edited" && ` to “${decision.final_value}”`}
        </p>
      ) : (
        canReview &&
        (editing ? (
          <form onSubmit={save} aria-label={`Edit ${name}`}>
            <input
              aria-label="Value"
              required
              maxLength={120}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <div className="actions">
              <button type="submit" disabled={busy || !value.trim()}>
                Save
              </button>
              <button type="button" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div className="actions">
            <button
              type="button"
              disabled={busy}
              aria-label={`Accept ${name}`}
              onClick={() => onDecide("accepted")}
            >
              Accept
            </button>
            <button
              type="button"
              disabled={busy}
              aria-label={`Edit ${name}`}
              onClick={() => setEditing(true)}
            >
              Edit
            </button>
            <button
              type="button"
              disabled={busy}
              aria-label={`Reject ${name}`}
              onClick={() => onDecide("rejected")}
            >
              Reject
            </button>
          </div>
        ))
      )}
    </li>
  );
}
