import { useEffect, useState } from "react";

import { api, describeError } from "./api";
import type { components } from "./api-schema";
import { POLL_MS } from "./ListingMedia";
import { AiTag } from "./ui";

type Scan = components["schemas"]["ComplianceScanOut"];
type Finding = components["schemas"]["ComplianceFinding"];
type Review = components["schemas"]["FindingReviewOut"];
type Decision = components["schemas"]["ComplianceDecisionOut"];

export const SEVERITY_TEXT: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

const NOT_REVIEWED: Review = {
  state: "open",
  decision: null,
  appeal: null,
  appeal_decision: null,
};

const FIELD_TEXT: Record<string, string> = {
  title: "Title",
  remarks: "Remarks",
};

const by = (d: Decision) => d.decided_by_name || "a reviewer";
const withNote = (d: Decision) => (d.note ? `: ${d.note}` : "");
// The note as the end of a sentence, without doubling its own full stop.
const ending = (d: Decision) =>
  d.note ? `: ${d.note}${/[.!?]$/.test(d.note) ? "" : "."}` : ".";

/** One line saying where a finding's review stands. */
export function reviewText(review: Review): string {
  const { decision, appeal, appeal_decision: ruling } = review;
  switch (review.state) {
    case "open":
      return "Waiting for review";
    case "accepted":
      return `Confirmed as an issue by ${by(decision!)}${withNote(decision!)}`;
    case "dismissed":
      return `Dismissed by ${by(decision!)}${withNote(decision!)}`;
    case "edits_requested":
      return `Edits requested by ${by(decision!)}${withNote(decision!)}`;
    case "appealed":
      return `Appealed by ${by(appeal!)}${ending(appeal!)} Waiting for another reviewer.`;
    case "upheld":
      return `Appeal rejected by ${by(ruling!)}${ending(ruling!)} The decision stands.`;
    case "overturned":
      return `Appeal accepted by ${by(ruling!)}${ending(ruling!)} The finding is set aside.`;
  }
}

/** The phrase in its sentence, with the matched words marked. */
export function Evidence({
  text,
  finding,
}: {
  text: string;
  finding: Finding;
}) {
  const from = Math.max(0, finding.start - 40);
  const to = Math.min(text.length, finding.end + 40);
  return (
    <q className="evidence">
      {from > 0 && "…"}
      {text.slice(from, finding.start)}
      <mark>{text.slice(finding.start, finding.end)}</mark>
      {text.slice(finding.end, to)}
      {to < text.length && "…"}
    </q>
  );
}

export function FindingFacts({ finding }: { finding: Finding }) {
  return (
    <>
      <p>
        <strong>{finding.rule_title}</strong>
        <span className={`badge severity-${finding.severity}`}>
          {SEVERITY_TEXT[finding.severity]} severity
        </span>
        <br />
        <small className="confidence">
          <span
            className={finding.confidence < 0.6 ? "meter low" : "meter"}
            aria-hidden="true"
          >
            <span
              style={{ width: `${Math.round(finding.confidence * 100)}%` }}
            />
          </span>
          Rule {finding.rule_id}, {FIELD_TEXT[finding.field]},{" "}
          {finding.source === "rule" ? "word rule" : "AI check"},{" "}
          {Math.round(finding.confidence * 100)}% confidence
        </small>
      </p>
      <p>{finding.explanation}</p>
      <p>
        <small>Suggestion: {finding.suggestion}</small>
      </p>
    </>
  );
}

/** Policy check of the listing's title and remarks, with review and appeal per finding.
 * Only the organisation that owns the listing sees it.
 */
export function ListingCompliance({
  listingId,
  listingVersion,
  canRequest,
}: {
  listingId: string;
  listingVersion: number;
  canRequest: boolean;
}) {
  const [scans, setScans] = useState<Scan[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    api<Scan[]>(`/listings/${listingId}/compliance/scans`)
      .then((list) => {
        if (cancelled) return;
        setScans(list);
        setLoadError(null);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
    // A new listing version may mean a scan started on submit.
  }, [listingId, listingVersion, reloadKey]);

  const scan = scans?.[0];
  const working = scan?.status === "queued" || scan?.status === "running";
  useEffect(() => {
    if (!working) return;
    // Keyed on each load attempt, so one failed check does not stop polling.
    const timer = setTimeout(reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [working, reloadKey]);

  async function act(path: string, body?: object) {
    setBusy(true);
    setActionError(null);
    try {
      await api(path, { method: "POST", body });
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
    reload();
  }

  const output = scan?.status === "succeeded" ? scan.output : null;

  return (
    <section aria-labelledby="compliance-heading" id="policy-check">
      <div className="panel-head">
        <h3 id="compliance-heading">Policy check</h3>
        <AiTag>AI + rules</AiTag>
      </div>
      <p>
        <small>
          Checks the title and remarks for phrases that may break the listing
          policy, so a person can look at them. It is not a legal review: a
          check with no findings does not mean the listing is lawful. Nothing is
          changed or hidden automatically.
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
      {!scans && !loadError && <p className="loading">Loading…</p>}
      {scans && !scan && <p>Not checked yet.</p>}
      {working && (
        <p role="status">
          {scan.status === "queued" ? "Waiting to check…" : "Checking…"}
        </p>
      )}
      {scan?.status === "failed" && (
        <p role="alert">The check failed: {scan.error}</p>
      )}
      {canRequest && scans && !working && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void act(`/listings/${listingId}/compliance/scans`)}
        >
          {scan ? "Check again" : "Check title and remarks"}
        </button>
      )}

      {scan && output && (
        <>
          <p>
            <small>
              {output.policy_name}, version {output.policy_version} (
              {output.jurisdiction}). {output.policy_notice}
            </small>
          </p>
          {scan.listing_version !== listingVersion && (
            <p className="notice" role="note">
              The listing changed after this check. Check again to see the
              current text.
            </p>
          )}
          {!output.model_checked && (
            <p className="notice" role="note">
              Only the policy&apos;s word rules ran; the AI check did not.{" "}
              {output.model_note}
              {scan.is_demo && <span className="badge">Demo</span>}
            </p>
          )}
          {output.findings.length === 0 ? (
            <p>
              No findings under {output.policy_name} {output.policy_version}.
              This is not a legal review.
            </p>
          ) : (
            <ol className="finding-list" aria-label="Findings">
              {output.findings.map((finding, index) => (
                <FindingItem
                  key={index}
                  index={index}
                  finding={finding}
                  text={
                    finding.field === "title"
                      ? scan.checked_title
                      : scan.checked_remarks
                  }
                  review={scan.reviews[index] ?? NOT_REVIEWED}
                  scan={scan}
                  busy={busy}
                  onPost={(suffix, body) =>
                    void act(
                      `/compliance/scans/${scan.id}/findings/${index}/${suffix}`,
                      body,
                    )
                  }
                />
              ))}
            </ol>
          )}
          {!scan.review_open && output.findings.length > 0 && (
            <p>
              <small>
                A newer check replaced this one; its decisions are kept for the
                record.
              </small>
            </p>
          )}
        </>
      )}
    </section>
  );
}

function FindingItem({
  index,
  finding,
  text,
  review,
  scan,
  busy,
  onPost,
}: {
  index: number;
  finding: Finding;
  text: string;
  review: Review;
  scan: Scan;
  busy: boolean;
  onPost: (suffix: string, body: object) => void;
}) {
  const [note, setNote] = useState("");
  const label = `finding ${index + 1}`;
  const canDecide = scan.review_open && scan.can_review;
  const canAppeal =
    scan.review_open &&
    scan.can_appeal &&
    (review.state === "accepted" || review.state === "edits_requested");

  return (
    <li>
      <Evidence text={text} finding={finding} />
      <FindingFacts finding={finding} />
      <p className="decision">{reviewText(review)}</p>
      {review.appeal && <Trail review={review} />}

      {canDecide && review.state === "open" && (
        <div role="group" aria-label={`Review ${label}`}>
          <label className="note-field">
            Note (needed for a request for edits)
            <input
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="actions">
            {(
              [
                ["accepted", "Confirm issue"],
                ["dismissed", "Dismiss"],
                ["edits_requested", "Request edits"],
              ] as const
            ).map(([decision, text]) => (
              <button
                key={decision}
                type="button"
                disabled={
                  busy || (decision === "edits_requested" && !note.trim())
                }
                onClick={() =>
                  onPost("decision", {
                    decision,
                    note: note.trim() || undefined,
                  })
                }
              >
                {text}
              </button>
            ))}
          </div>
        </div>
      )}

      {canAppeal && (
        <form
          aria-label={`Appeal ${label}`}
          onSubmit={(e) => {
            e.preventDefault();
            onPost("appeal", { reason: note.trim() });
          }}
        >
          <label className="note-field">
            Why the decision is wrong
            <input
              required
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="actions">
            <button type="submit" disabled={busy || !note.trim()}>
              Appeal
            </button>
          </div>
        </form>
      )}

      {canDecide && review.state === "appealed" && (
        <div role="group" aria-label={`Rule on the appeal of ${label}`}>
          <label className="note-field">
            Reason for the ruling
            <input
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="actions">
            {(
              [
                ["upheld", "Uphold decision"],
                ["overturned", "Overturn decision"],
              ] as const
            ).map(([decision, text]) => (
              <button
                key={decision}
                type="button"
                disabled={busy || !note.trim()}
                onClick={() =>
                  onPost("appeal/decision", { decision, note: note.trim() })
                }
              >
                {text}
              </button>
            ))}
          </div>
        </div>
      )}
    </li>
  );
}

const STEP_TEXT: Record<string, string> = {
  accepted: "Confirmed as an issue",
  dismissed: "Dismissed",
  edits_requested: "Edits requested",
  appealed: "Appealed",
  upheld: "Appeal rejected",
  overturned: "Appeal accepted",
};

/** Every step of an appealed finding, in order, with who and when. */
function Trail({ review }: { review: Review }) {
  const steps = [review.decision, review.appeal, review.appeal_decision];
  return (
    <ol className="trail" aria-label="Review trail">
      {steps.map(
        (step) =>
          step && (
            <li key={step.decision}>
              {STEP_TEXT[step.decision] ?? step.decision} by {by(step)},{" "}
              {new Date(step.decided_at).toLocaleString("en-IN")}
              {withNote(step)}
            </li>
          ),
      )}
    </ol>
  );
}
