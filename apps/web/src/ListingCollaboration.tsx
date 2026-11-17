import { useEffect, useState, type FormEvent } from "react";

import { api, describeError, useAction, useList } from "./api";
import type { components } from "./api-schema";

type Assignment = components["schemas"]["AssignmentOut"];
type Comment = components["schemas"]["CommentOut"];
type Activity = components["schemas"]["ActivityOut"];
type Member = components["schemas"]["MemberOut"];

const WORKERS = ["mls_admin", "brokerage_admin", "broker", "agent"];
const when = (iso: string) => new Date(iso).toLocaleString("en-IN");

/** Assignment, comments and private notes, and the activity timeline of a listing.
 * Only the organisation that owns the listing sees this section.
 */
export function ListingCollaboration({
  listingId,
  organisationId,
  myUserId,
  canEdit,
  canWrite,
}: {
  listingId: string;
  organisationId: string;
  myUserId: string;
  canEdit: boolean;
  canWrite: boolean;
}) {
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);
  return (
    <section aria-labelledby="collab-heading">
      <h3 id="collab-heading">Team</h3>
      <AssignmentPanel
        listingId={listingId}
        organisationId={organisationId}
        canEdit={canEdit}
        reloadKey={reloadKey}
        onChange={reload}
      />
      <Comments
        listingId={listingId}
        myUserId={myUserId}
        canWrite={canWrite}
        reloadKey={reloadKey}
        onChange={reload}
      />
      <Timeline listingId={listingId} reloadKey={reloadKey} />
    </section>
  );
}

function AssignmentPanel({
  listingId,
  organisationId,
  canEdit,
  reloadKey,
  onChange,
}: {
  listingId: string;
  organisationId: string;
  canEdit: boolean;
  reloadKey: number;
  onChange: () => void;
}) {
  const [assignment, setAssignment] = useState<Assignment | null | undefined>();
  const [choice, setChoice] = useState("");
  const members = useList<Member>(
    "/organisations/current/members",
    organisationId,
  );
  const action = useAction();

  useEffect(() => {
    let cancelled = false;
    api<Assignment | null>(`/listings/${listingId}/assignment`)
      .then((row) => !cancelled && setAssignment(row))
      .catch(() => !cancelled && setAssignment(null));
    return () => {
      cancelled = true;
    };
  }, [listingId, reloadKey]);

  function save(userId: string | null) {
    void action.run(async () => {
      await api(`/listings/${listingId}/assignment`, {
        method: "PUT",
        body: { user_id: userId },
      });
      setChoice("");
      onChange();
    });
  }

  const workers = (members.items ?? []).filter((m) => WORKERS.includes(m.role));
  return (
    <div>
      <p>
        Assigned to:{" "}
        {assignment ? (
          <strong>{assignment.user_name}</strong>
        ) : (
          "nobody besides the listing agent"
        )}
        {assignment?.note && <> — {assignment.note}</>}
      </p>
      {canEdit && (
        <p>
          <label>
            Assign to{" "}
            <select value={choice} onChange={(e) => setChoice(e.target.value)}>
              <option value="">Choose a teammate</option>
              {workers.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.full_name}
                </option>
              ))}
            </select>
          </label>{" "}
          <button
            type="button"
            disabled={!choice || action.busy}
            onClick={() => save(choice)}
          >
            Assign
          </button>{" "}
          {assignment && (
            <button
              type="button"
              disabled={action.busy}
              onClick={() => save(null)}
            >
              Clear
            </button>
          )}
        </p>
      )}
      {action.error && <p role="alert">{action.error}</p>}
    </div>
  );
}

function Comments({
  listingId,
  myUserId,
  canWrite,
  reloadKey,
  onChange,
}: {
  listingId: string;
  myUserId: string;
  canWrite: boolean;
  reloadKey: number;
  onChange: () => void;
}) {
  const [comments, setComments] = useState<Comment[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<"team" | "private">("team");
  const [editing, setEditing] = useState<{ id: string; body: string } | null>(
    null,
  );
  const action = useAction();

  useEffect(() => {
    let cancelled = false;
    api<Comment[]>(`/listings/${listingId}/comments`)
      .then((rows) => !cancelled && setComments(rows))
      .catch((error) => !cancelled && setLoadError(describeError(error)));
    return () => {
      cancelled = true;
    };
  }, [listingId, reloadKey]);

  function add(event: FormEvent) {
    event.preventDefault();
    void action.run(async () => {
      await api(`/listings/${listingId}/comments`, {
        method: "POST",
        body: { body, visibility },
      });
      setBody("");
      onChange();
    });
  }

  function change(path: string, method: string, payload?: object) {
    void action.run(async () => {
      await api(path, { method, body: payload });
      setEditing(null);
      onChange();
    });
  }

  return (
    <div>
      <h4>Comments</h4>
      {loadError && <p role="alert">{loadError}</p>}
      {comments?.length === 0 && <p>No comments yet.</p>}
      {comments && comments.length > 0 && (
        <ol aria-label="Comments" className="finding-list">
          {comments.map((c) => (
            <li key={c.id}>
              <p>
                <strong>{c.author_name}</strong>{" "}
                <small>
                  {when(c.created_at)}
                  {c.visibility === "private" && " · private note, only you"}
                  {c.edited_at && !c.deleted_at && " · edited"}
                </small>
              </p>
              {c.deleted_at ? (
                <p>
                  <em>Comment deleted.</em>
                </p>
              ) : editing?.id === c.id ? (
                <p>
                  <label>
                    Edit comment{" "}
                    <textarea
                      value={editing.body}
                      onChange={(e) =>
                        setEditing({ id: c.id, body: e.target.value })
                      }
                    />
                  </label>{" "}
                  <button
                    type="button"
                    disabled={action.busy || !editing.body.trim()}
                    onClick={() =>
                      change(`/comments/${c.id}`, "PATCH", {
                        body: editing.body,
                      })
                    }
                  >
                    Save
                  </button>{" "}
                  <button type="button" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </p>
              ) : (
                <p>{c.body}</p>
              )}
              {c.author_user_id === myUserId &&
                !c.deleted_at &&
                editing?.id !== c.id && (
                  <p>
                    <button
                      type="button"
                      onClick={() => setEditing({ id: c.id, body: c.body })}
                    >
                      Edit
                    </button>{" "}
                    <button
                      type="button"
                      disabled={action.busy}
                      onClick={() => change(`/comments/${c.id}`, "DELETE")}
                    >
                      Delete
                    </button>
                  </p>
                )}
            </li>
          ))}
        </ol>
      )}
      {canWrite && (
        <form onSubmit={add} aria-label="New comment">
          <p>
            <label>
              Comment{" "}
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                required
                maxLength={5000}
              />
            </label>
          </p>
          <p>
            <label>
              <input
                type="checkbox"
                checked={visibility === "private"}
                onChange={(e) =>
                  setVisibility(e.target.checked ? "private" : "team")
                }
              />{" "}
              Private note (only you see it; nobody is notified)
            </label>
          </p>
          <button type="submit" disabled={action.busy || !body.trim()}>
            {visibility === "private" ? "Save note" : "Post comment"}
          </button>
        </form>
      )}
      {action.error && <p role="alert">{action.error}</p>}
    </div>
  );
}

function Timeline({
  listingId,
  reloadKey,
}: {
  listingId: string;
  reloadKey: number;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Activity[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api<Activity[]>(`/listings/${listingId}/activity`)
      .then((rows) => !cancelled && setItems(rows))
      .catch((caught) => !cancelled && setError(describeError(caught)));
    return () => {
      cancelled = true;
    };
  }, [listingId, open, reloadKey]);

  return (
    <div>
      <h4>Activity</h4>
      <button type="button" onClick={() => setOpen(!open)}>
        {open ? "Hide activity" : "Show activity"}
      </button>
      {open && error && <p role="alert">{error}</p>}
      {open && items?.length === 0 && <p>Nothing yet.</p>}
      {open && items && items.length > 0 && (
        <ol aria-label="Activity">
          {items.map((item, index) => (
            <li key={`${item.at}-${index}`}>
              <small>{when(item.at)}</small> {item.actor_name ?? "The system"}{" "}
              {item.kind === "comment" && !item.action.endsWith("deleted")
                ? `commented${item.visibility === "private" ? " (private)" : ""}: “${item.summary}”`
                : item.summary}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
