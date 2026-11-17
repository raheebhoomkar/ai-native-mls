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
import { ImportSourceDetails } from "./ListingImport";
import { ListingMedia } from "./ListingMedia";
import { ListingCompliance } from "./ListingCompliance";
import { ListingLocation } from "./ListingLocation";
import { ListingValuation } from "./ListingValuation";
import { ListingWorkflow } from "./ListingWorkflow";
import { ListingCollaboration } from "./ListingCollaboration";
import { ListingRedaction } from "./ListingRedaction";
import { ListingSuggestions } from "./ListingSuggestions";
import { formatMoney, type Listing, STATUS_LABELS } from "./Listings";
import { Icon, initials, PlaceholderArt } from "./ui";

type Status = Listing["status"];
type StatusChange = components["schemas"]["StatusChangeOut"];
type Media = components["schemas"]["MediaOut"];

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

/** Status changes that move a listing forward get the primary style; leaving the market is marked. */
function transitionStyle(to: Status): string | undefined {
  if (to === "active" || to === "pending_review") return "primary";
  if (to === "withdrawn" || to === "expired") return "danger";
  return undefined;
}

/** The listing's photos, large; decoration only, since the gallery below names each one. */
function Hero({ media }: { media: Media[] | null }) {
  if (media === null)
    return (
      <div className="listing-hero empty-hero skeleton" aria-hidden="true" />
    );
  const photos = media.filter((item) => item.thumbnail_url).slice(0, 5);
  if (photos.length === 0)
    return (
      <div className="listing-hero empty-hero">
        <PlaceholderArt>
          <span>Photography to come</span>
        </PlaceholderArt>
      </div>
    );
  return (
    <div className="listing-hero" data-count={photos.length}>
      {photos.map((photo, index) => (
        <div key={photo.id}>
          <img src={index === 0 ? photo.url : photo.thumbnail_url!} alt="" />
          {index === 0 && media.length > 1 && (
            <button
              type="button"
              className="hero-more small"
              onClick={() =>
                document
                  .getElementById("media-heading")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              <Icon name="image" />
              All {media.length} photos
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

type Loaded =
  | { state: "loading" }
  | { state: "missing" }
  | { state: "error"; message: string }
  | { state: "ready"; listing: Listing };

export function ListingDetail({
  organisation,
  myUserId = "",
}: {
  organisation: CurrentOrganisation;
  myUserId?: string;
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
  // The gallery's latest photo list, shared with the redaction panel.
  const [media, setMedia] = useState<Media[] | null>(null);

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

  if (loaded.state === "loading") return <p className="loading">Loading…</p>;
  if (loaded.state === "missing")
    return (
      <section className="empty">
        <Icon name="grid" />
        <h2>Listing not found</h2>
        <p>It does not exist, or it is not shared with {organisation.name}.</p>
        <Link className="button-link" to="/listings">
          Back to listings
        </Link>
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

  const place = [address.locality, address.city].filter(Boolean).join(", ");
  const canManage = listing.can_edit || listing.allowed_transitions.length > 0;

  return (
    <section aria-labelledby="listing-heading">
      <p className="crumbs">
        <Link to="/listings">← Listings</Link>
      </p>
      <Hero media={media} />

      <header className="listing-header">
        <div>
          <p className="eyebrow">
            {PROPERTY_TYPE_LABELS[property.property_type]}
            {place && ` · ${place}`}
          </p>
          <h2 id="listing-heading">{listing.title}</h2>
          <p className="listing-meta">
            <strong className={`status-pill status-${listing.status}`}>
              {STATUS_LABELS[listing.status]}
            </strong>
            {listing.archived_at && <span className="badge">Archived</span>}
            <span>
              {listing.listing_type === "sale" ? "For sale" : "For rent"}
            </span>
            <span>
              {listing.visibility === "network"
                ? "Shared on the network"
                : "Private listing"}
            </span>
          </p>
        </div>
        <div className="listing-price">
          <span className="price-label">List price</span>
          <span className="price-value">{formatMoney(listing.list_price)}</span>
        </div>
      </header>

      {!isOwn && (
        <p className="notice">
          Shared by {listing.organisation_name}. You can view this listing but
          not change it.
        </p>
      )}

      <ul className="specs" aria-label="Key facts">
        <li>
          <span className="spec-value">
            {PROPERTY_TYPE_LABELS[property.property_type]}
          </span>
          <span className="spec-label">Property type</span>
        </li>
        {property.bedrooms != null && (
          <li>
            <span className="spec-value">{property.bedrooms}</span>
            <span className="spec-label">Bedrooms</span>
          </li>
        )}
        {property.bathrooms != null && (
          <li>
            <span className="spec-value">{property.bathrooms}</span>
            <span className="spec-label">Bathrooms</span>
          </li>
        )}
        {property.area && (
          <li>
            <span className="spec-value">
              {Number(property.area.value).toLocaleString("en-IN")}
            </span>
            <span className="spec-label">
              {property.area.unit === "sqft" ? "Square feet" : "Square metres"}
            </span>
          </li>
        )}
        {property.year_built != null && (
          <li>
            <span className="spec-value">{property.year_built}</span>
            <span className="spec-label">Year built</span>
          </li>
        )}
      </ul>

      <div className="listing-body">
        <div className="listing-main">
          <section aria-labelledby="details-heading">
            <h3 id="details-heading">Details</h3>
            <dl className="details">
              <dt>Property</dt>
              <dd>
                {PROPERTY_TYPE_LABELS[property.property_type]}
                {property.bedrooms != null && ` · ${property.bedrooms} bed`}
                {property.bathrooms != null && ` · ${property.bathrooms} bath`}
                {property.area &&
                  ` · ${property.area.value} ${property.area.unit === "sqft" ? "sq ft" : "sq m"}`}
                {property.year_built != null &&
                  ` · built ${property.year_built}`}
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
                    {formatMoney(listing.sold_price)} (reported by the listing
                    agent, not verified)
                  </dd>
                </>
              )}
              <dt>Remarks</dt>
              <dd className="remarks">{listing.remarks || "None"}</dd>
              {isOwn && <ImportSourceDetails listingId={listing.id} />}
            </dl>
          </section>

          <ListingMedia
            listingId={listing.id}
            canManage={listing.can_edit}
            onLoaded={setMedia}
          />
          <ListingLocation
            key={`${property.id}:${reloads}`}
            property={property}
            title={listing.title}
            isOwn={isOwn}
            canEdit={listing.can_edit && !listing.archived_at}
          />
          <ListingRedaction
            listingId={listing.id}
            media={media}
            canRequest={listing.can_edit && !listing.archived_at}
          />

          {isOwn && (
            <ListingCompliance
              listingId={listing.id}
              listingVersion={listing.version}
              canRequest={listing.can_edit && !listing.archived_at}
            />
          )}

          {isOwn && (
            <ListingWorkflow
              listingId={listing.id}
              canRequest={listing.can_edit && !listing.archived_at}
            />
          )}

          {isOwn && <ListingValuation listingId={listing.id} />}

          {isOwn && (
            <ListingCollaboration
              listingId={listing.id}
              organisationId={organisation.id}
              myUserId={myUserId}
              canEdit={listing.can_edit && !listing.archived_at}
              canWrite={organisation.my_permissions.includes("listing:write")}
            />
          )}

          {isOwn && (
            <section aria-labelledby="history-heading">
              <History listingId={listing.id} version={listing.version} />
            </section>
          )}
        </div>

        <aside className="listing-aside" aria-label="Agent and actions">
          <div className="panel agent-card">
            <span className="eyebrow">Presented by</span>
            <span className="avatar large" aria-hidden="true">
              {initials(listing.listing_agent.full_name)}
            </span>
            <span className="agent-name">
              {listing.listing_agent.full_name}
            </span>
            <span className="agent-org">{listing.organisation_name}</span>
          </div>

          {(canManage || conflict || error) && (
            <section className="manage" aria-labelledby="manage-heading">
              <h3 id="manage-heading">Manage listing</h3>
              {conflict && (
                <div className="notice" role="alert">
                  <p>
                    Someone else changed this listing. Reload it, then try
                    again.
                  </p>
                  <button type="button" onClick={reload}>
                    Reload listing
                  </button>
                </div>
              )}
              {error && <p role="alert">{error}</p>}

              {canManage && (
                <div className="actions">
                  {listing.can_edit && listing.status !== "sold" && (
                    <Link
                      className="button-link"
                      to={`/listings/${listing.id}/edit`}
                    >
                      Edit
                    </Link>
                  )}
                  {listing.allowed_transitions.map((to) => (
                    <button
                      key={to}
                      type="button"
                      className={transitionStyle(to)}
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
                      className="danger"
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
                <form
                  onSubmit={confirmTransition}
                  aria-label="Confirm status change"
                >
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
                      <small>
                        Marking as sold is final and cannot be undone.
                      </small>
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
                    Archive this listing? It leaves the listing table and can no
                    longer be edited.
                  </p>
                  <div className="actions">
                    <button
                      type="button"
                      className="danger"
                      disabled={busy}
                      onClick={archive}
                    >
                      Confirm archive
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmArchive(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}

          <ListingSuggestions
            listingId={listing.id}
            canRequest={listing.can_edit && !listing.archived_at}
          />
        </aside>
      </div>
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
      <h3 id="history-heading">Status history</h3>
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
