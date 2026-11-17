import { useEffect, useState } from "react";

import { api, describeError } from "./api";
import type { components } from "./api-schema";
import { POLL_MS } from "./ListingMedia";
import { AiTag } from "./ui";

type Media = components["schemas"]["MediaOut"];
type Run = components["schemas"]["RedactionRunOut"];
type Region = components["schemas"]["Region"];

const CATEGORY_TEXT: Record<string, string> = {
  face: "Face",
  licence_plate: "Licence plate",
  phone_number: "Phone number",
  watermark: "Watermark",
  signage: "Sign",
};

const REVIEW_TEXT: Record<string, string> = {
  pending: "Waiting for review",
  approved: "Approved",
  rejected: "Rejected",
};

const category = (name: string) => CATEGORY_TEXT[name] ?? name;

/** Blurred copies of the listing's photos, each approved or rejected by a person. */
export function ListingRedaction({
  listingId,
  media,
  canRequest,
}: {
  listingId: string;
  media: Media[] | null;
  canRequest: boolean;
}) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);
  // Photos added or removed in the gallery change which checks are listed.
  const mediaIds = media?.map((m) => m.id).join(",");

  useEffect(() => {
    let cancelled = false;
    api<Run[]>(`/listings/${listingId}/redactions`)
      .then((list) => {
        if (cancelled) return;
        setRuns(list);
        setLoadError(null);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [listingId, reloadKey, mediaIds]);

  // Newest check of each photo; older ones stay in the API for the record.
  const latest = new Map<string, Run>();
  for (const run of runs ?? []) {
    if (!latest.has(run.media_asset_id)) latest.set(run.media_asset_id, run);
  }
  const working = [...latest.values()].some(
    (run) => run.status === "queued" || run.status === "running",
  );
  useEffect(() => {
    if (!working) return;
    // Keyed on each load attempt, so one failed check does not stop polling.
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

  const check = (mediaId: string) =>
    act(() => api(`/media/${mediaId}/redactions`, { method: "POST" }));

  const decide = (runId: string, decision: string, note: string) =>
    act(() =>
      api(`/ai/redactions/${runId}/decision`, {
        method: "POST",
        body: { decision, note: note.trim() || undefined },
      }),
    );

  return (
    <section aria-labelledby="redaction-heading" className="redaction">
      <div className="panel-head">
        <h3 id="redaction-heading">Privacy redaction</h3>
        <AiTag>Image analysis</AiTag>
      </div>
      <p>
        <small>
          Makes a copy of a photo with faces, licence plates, phone numbers,
          watermarks and signs blurred. Detection is automatic: it can miss
          things or blur the wrong area, so a person approves each copy. The
          original photo is never changed.
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
      {(!media || !runs) && !loadError && <p className="loading">Loading…</p>}
      {media?.length === 0 && <p>No photos yet.</p>}

      {media && runs && media.length > 0 && (
        <ul className="redaction-list">
          {media.map((item) => {
            const run = latest.get(item.id);
            const runWorking =
              run?.status === "queued" || run?.status === "running";
            return (
              <li key={item.id}>
                <strong className="caption">{item.filename}</strong>
                {item.status !== "ready" ? (
                  <p>Available once the photo has finished processing.</p>
                ) : !run ? (
                  <p>Not checked yet.</p>
                ) : runWorking ? (
                  <p role="status">
                    {run.status === "queued"
                      ? "Waiting to check…"
                      : "Checking for sensitive content…"}
                  </p>
                ) : run.status === "failed" ? (
                  <p role="alert">The check failed: {run.error}</p>
                ) : null}
                {canRequest && item.status === "ready" && !runWorking && (
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`Check ${item.filename} for sensitive content`}
                    onClick={() => void check(item.id)}
                  >
                    {!run
                      ? "Check for sensitive content"
                      : run.status === "failed"
                        ? "Try again"
                        : "Check again"}
                  </button>
                )}
                {run?.status === "succeeded" && run.output && (
                  <Preview
                    run={run}
                    original={item}
                    busy={busy}
                    onDecide={(decision, note) =>
                      void decide(run.id, decision, note)
                    }
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Preview({
  run,
  original,
  busy,
  onDecide,
}: {
  run: Run;
  original: Media;
  busy: boolean;
  onDecide: (decision: "accepted" | "rejected", note: string) => void;
}) {
  const [note, setNote] = useState("");
  const output = run.output!;

  return (
    <div>
      <p className="decision">
        {REVIEW_TEXT[run.review_status ?? "pending"]}
        {run.decision?.note && `: ${run.decision.note}`}
      </p>
      <div className="redaction-preview">
        <figure>
          <div className="boxed">
            <img src={original.url} alt={`${original.filename}, original`} />
            {output.regions.map((region, index) => (
              <span
                key={index}
                className={region.uncertain ? "box uncertain" : "box"}
                style={{
                  left: `${region.box[0] * 100}%`,
                  top: `${region.box[1] * 100}%`,
                  width: `${region.box[2] * 100}%`,
                  height: `${region.box[3] * 100}%`,
                }}
                title={category(region.category)}
              />
            ))}
          </div>
          <figcaption>Original, with the areas found outlined</figcaption>
        </figure>
        <figure>
          {run.redacted_url && (
            <img
              src={run.redacted_url}
              alt={`${original.filename}, redacted copy`}
            />
          )}
          <figcaption>
            Redacted copy
            {run.is_demo && <span className="badge">Demo</span>}
          </figcaption>
        </figure>
      </div>

      {output.regions.length === 0 ? (
        <p>
          Nothing was found. That does not prove there is nothing to hide: look
          at the photo before approving.
        </p>
      ) : (
        <ul className="region-list" aria-label="Areas blurred">
          {output.regions.map((region, index) => (
            <RegionItem key={index} region={region} />
          ))}
        </ul>
      )}
      {output.unchecked.map((gap) => (
        <p key={gap.categories.join()} className="notice" role="note">
          Not checked: {gap.categories.map(category).join(", ")}. {gap.reason}
        </p>
      ))}
      <p>
        <small>
          Checked with{" "}
          {output.checked.map((c) => `${c.detector} (${c.version})`).join(", ")}
          . Policy version {output.policy_version}.
        </small>
      </p>

      {run.review_status === "pending" && run.can_review && (
        <div
          role="group"
          aria-label={`Review the redacted copy of ${original.filename}`}
        >
          <label className="note-field">
            Note (optional)
            <input
              maxLength={500}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide("accepted", note)}
            >
              Approve copy
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide("rejected", note)}
            >
              Reject copy
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function RegionItem({ region }: { region: Region }) {
  return (
    <li>
      <strong>{category(region.category)}</strong>{" "}
      <small>
        {region.detector},{" "}
        {region.confidence == null
          ? "no score"
          : `${Math.round(region.confidence * 100)}% confident`}
      </small>
      {region.uncertain && <span className="badge">Uncertain</span>}
      {region.note && (
        <>
          <br />
          <small>{region.note}</small>
        </>
      )}
    </li>
  );
}
