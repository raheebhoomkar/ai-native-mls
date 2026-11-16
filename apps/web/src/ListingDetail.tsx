import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  api,
  ApiError,
  type CurrentOrganisation,
  describeError,
  useList,
} from "./api";
import type { components } from "./api-schema";
import { ListingMedia } from "./ListingMedia";
import { formatMoney, type Listing, STATUS_LABELS } from "./Listings";

type Status = Listing["status"];
type StatusChange = components["schemas"]["StatusChangeOut"];

const PROPERTY_TYPE_LABELS: Record<
  Listing["property"]["property_type"],
  string
> = {
  apartment: "Apartment",
  house: "House",
  villa: "Villa",
  plot: "Plot",
  commercial: "Commercial",
  other: "Other",
};

/** Button text for moving a listing to `to`; approval and relisting both lead to "active". */
function transitionLabel(from: Status, to: Status): string {
  if (to === "active")
    return from === "pending_review"
      ? "Approve and publish"
      : "Return to market";
  return {
    draft: "Return to draft",
    pending_review: "Submit for review",
    temporarily_off_market: "Take off market temporarily",
    sold: "Mark as sold",
    withdrawn: "Withdraw",
    expired: "Mark as expired",
  }[to];
}

const when = (iso: string) => new Date(iso).toLocaleString();

type Loaded =
  | { state: "loading" }
  | { state: "missing" }
  | { state: "error"; message: string }
  | { state: "ready"; listing: Listing };

export function ListingDetail({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [reloads, setReloads] = useState(0);
  // The status change being confirmed, if any.
  const [target, setTarget] = useState<Status | null>(null);
  const [reason, setReason] = useState("");
  const [soldPrice, setSoldPrice] = useState("");
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<Listing>(`/listings/${id}`)
      .then((listing) => !cancelled && setLoaded({ state: "ready", listing }))
      .catch((caught) => {
        if (cancelled) return;
        setLoaded(
          caught instanceof ApiError &&
            (caught.status === 404 || caught.status === 422)
            ? { state: "missing" }
            : { state: "error", message: describeError(caught) },
        );
      });
    return () => {
      cancelled = true;
    };
  }, [id, organisation.id, reloads]);

  if (loaded.state === "loading") return <p>Loading…</p>;
  if (loaded.state === "missing")
    return (
      <section>
        <h2>Listing not found</h2>
        <p>It does not exist, or it is not shared with {organisation.name}.</p>
        <Link to="/listings">Back to listings</Link>
      </section>
    );
  if (loaded.state === "error")
    return (
      <section>
        <p role="alert">{loaded.message}</p>
        <button type="button" onClick={() => setReloads((n) => n + 1)}>
          Try again
        </button>
      </section>
    );

  const listing = loaded.listing;
  const property = listing.property;
  const address = property.address;
  const isOwn = listing.organisation_id === organisation.id;
  const live = ["active", "pending_review", "temporarily_off_market"].includes(
    listing.status,
  );

  function reload() {
    setConflict(false);
    setError(null);
    setTarget(null);
    setConfirmArchive(false);
    setReloads((n) => n + 1);
  }

  /** Run a change; a version conflict offers a reload instead of a generic error. */
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "version_conflict")
        setConflict(true);
      else setError(describeError(caught));
    } finally {
      setBusy(false);
    }
  }

  function confirmTransition(event: FormEvent) {
    event.preventDefault();
    if (!target) return;
    void run(async () => {
      const updated = await api<Listing>(
        `/listings/${listing.id}/transitions`,
        {
          method: "POST",
          body: {
            to: target,
            version: listing.version,
            reason: reason.trim() || null,
            sold_price:
              target === "sold"
                ? { amount: soldPrice, currency: listing.list_price.currency }
                : null,
          },
        },
      );
      setLoaded({ state: "ready", listing: updated });
      setTarget(null);
      setReason("");
      setSoldPrice("");
    });
  }

  function archive() {
    void run(async () => {
      await api(`/listings/${listing.id}`, { method: "DELETE" });
      navigate("/listings");
    });
  }

  return (
    <section aria-labelledby="listing-heading">
      <p>
        <Link to="/listings">← Listings</Link>
      </p>
      <h2 id="listing-heading">{listing.title}</h2>
      <p>
        <strong>{STATUS_LABELS[listing.status]}</strong>
        {listing.archived_at && " · Archived"} ·{" "}
        {listing.listing_type === "sale" ? "For sale" : "For rent"} ·{" "}
        {formatMoney(listing.list_price)}
      </p>
      {!isOwn && (
        <p>
          Shared by {listing.organisation_name}. You can view this listing but
          not change it.
        </p>
      )}

      <dl>
        <dt>Property</dt>
        <dd>
          {PROPERTY_TYPE_LABELS[property.property_type]}
          {property.bedrooms != null && ` · ${property.bedrooms} bed`}
          {property.bathrooms != null && ` · ${property.bathrooms} bath`}
          {property.area &&
            ` · ${property.area.value} ${property.area.unit === "sqft" ? "sq ft" : "sq m"}`}
          {property.year_built != null && ` · built ${property.year_built}`}
        </dd>
        <dt>Address</dt>
        <dd>
          {[
            address.line1,
            address.line2,
            address.locality,
            address.city,
            address.state,
            address.postal_code,
            address.country,
          ]
            .filter(Boolean)
            .join(", ")}
        </dd>
        <dt>Listing agent</dt>
        <dd>
          {listing.listing_agent.full_name}, {listing.organisation_name}
        </dd>
        <dt>Visibility</dt>
        <dd>
          {listing.visibility === "network"
            ? "Shared with other organisations while active, off market or sold"
            : "Private to the listing organisation"}
        </dd>
        {listing.expires_on && (
          <>
            <dt>Expires on</dt>
            <dd>{listing.expires_on}</dd>
          </>
        )}
        {listing.listed_at && (
          <>
            <dt>First listed</dt>
            <dd>{when(listing.listed_at)}</dd>
          </>
        )}
        {listing.sold_price && (
          <>
            <dt>Sold price</dt>
            <dd>
              {formatMoney(listing.sold_price)} (reported by the listing agent,
              not verified)
            </dd>
          </>
        )}
        <dt>Remarks</dt>
        <dd className="remarks">{listing.remarks || "None"}</dd>
      </dl>

      {conflict && (
        <div className="notice" role="alert">
          <p>Someone else changed this listing. Reload it, then try again.</p>
          <button type="button" onClick={reload}>
            Reload listing
          </button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}

      {(listing.can_edit || listing.allowed_transitions.length > 0) && (
        <div className="actions">
          {listing.can_edit && listing.status !== "sold" && (
            <Link to={`/listings/${listing.id}/edit`}>Edit</Link>
          )}
          {listing.allowed_transitions.map((to) => (
            <button
              key={to}
              type="button"
              disabled={busy}
              onClick={() => {
                setTarget(to);
                setConfirmArchive(false);
              }}
            >
              {transitionLabel(listing.status, to)}
            </button>
          ))}
          {listing.can_edit && !live && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setConfirmArchive(true);
                setTarget(null);
              }}
            >
              Archive
            </button>
          )}
        </div>
      )}

      {target && (
        <form onSubmit={confirmTransition} aria-label="Confirm status change">
          <h3>{transitionLabel(listing.status, target)}</h3>
          {target === "sold" && (
            <>
              <label htmlFor="sold-price">
                Sold price ({listing.list_price.currency})
              </label>
              <input
                id="sold-price"
                type="number"
                required
                min="0.01"
                step="0.01"
                value={soldPrice}
                onChange={(e) => setSoldPrice(e.target.value)}
              />
              <small>Marking as sold is final and cannot be undone.</small>
            </>
          )}
          <label htmlFor="transition-reason">Reason (optional)</label>
          <input
            id="transition-reason"
            maxLength={2000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="actions">
            <button type="submit" disabled={busy}>
              Confirm
            </button>
            <button type="button" onClick={() => setTarget(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {confirmArchive && (
        <div className="notice">
          <p>
            Archive this listing? It leaves the listing table and can no longer
            be edited.
          </p>
          <div className="actions">
            <button type="button" disabled={busy} onClick={archive}>
              Confirm archive
            </button>
            <button type="button" onClick={() => setConfirmArchive(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <ListingMedia listingId={listing.id} canManage={listing.can_edit} />

      {isOwn && <History listingId={listing.id} version={listing.version} />}
    </section>
  );
}

function History({
  listingId,
  version,
}: {
  listingId: string;
  version: number;
}) {
  // Reloads whenever the listing changes, so a new status change appears at once.
  const history = useList<StatusChange>(
    `/listings/${listingId}/history`,
    version,
  );
  return (
    <>
      <h3>Status history</h3>
      {history.error && <p role="alert">{history.error}</p>}
      <ol className="history">
        {history.items.map((change) => (
          <li key={change.id}>
            {when(change.changed_at)}:{" "}
            {change.from_status
              ? `${STATUS_LABELS[change.from_status]} → ${STATUS_LABELS[change.to_status]}`
              : `Created as ${STATUS_LABELS[change.to_status]}`}
            {change.reason && ` — ${change.reason}`}
          </li>
        ))}
      </ol>
      {history.next && (
        <button type="button" onClick={() => void history.loadMore()}>
          Load more
        </button>
      )}
    </>
  );
}
