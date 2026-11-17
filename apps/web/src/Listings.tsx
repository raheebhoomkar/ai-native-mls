import { type CSSProperties, type FormEvent, useMemo, useState } from "react";
import { Link } from "react-router";

import { type CurrentOrganisation, useList } from "./api";
import type { components } from "./api-schema";
import { type Bounds, MapView } from "./MapView";
import { AiTag, Icon, PlaceholderArt } from "./ui";

export type Listing = components["schemas"]["ListingOut"];
type SearchHit = components["schemas"]["SearchHit"];
type Status = Listing["status"];

export const STATUS_LABELS: Record<Status, string> = {
  draft: "Draft",
  pending_review: "Pending review",
  active: "Active",
  temporarily_off_market: "Temporarily off market",
  sold: "Sold",
  withdrawn: "Withdrawn",
  expired: "Expired",
};

/** Display only. Amounts stay strings everywhere else so no precision is lost. */
export function formatMoney(money: { amount: string; currency: string }) {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: money.currency,
      maximumFractionDigits: 0,
    }).format(Number(money.amount));
  } catch {
    return `${money.currency} ${money.amount}`; // unknown currency code
  }
}

type Explanation = SearchHit["explanation"];

const placeOf = (listing: Listing) =>
  [listing.property.address.locality, listing.property.address.city]
    .filter(Boolean)
    .join(", ");

/** "Score 0.43 · words: sea, facing · filters: min price" for a semantic search hit. */
function matchText(explanation: Explanation, score: number | null) {
  return (
    `Score ${score?.toFixed(2)}` +
    (explanation.matched_words.length > 0
      ? ` · words: ${explanation.matched_words.join(", ")}`
      : "") +
    (explanation.filters.length > 0
      ? ` · filters: ${explanation.filters.join(", ").replace(/_/g, " ")}`
      : "")
  );
}

/** One listing as a card: photo, price, title, place and key facts. The title link covers the card. */
export function ListingCard({
  listing,
  index = 0,
  explanation = null,
  score = null,
}: {
  listing: Listing;
  index?: number;
  explanation?: Explanation | null;
  score?: number | null;
}) {
  const property = listing.property;
  return (
    <li style={{ "--i": index } as CSSProperties}>
      <article className="listing-card" aria-labelledby={`card-${listing.id}`}>
        <div className="card-media">
          {listing.cover_url ? (
            <img src={listing.cover_url} alt="" loading="lazy" />
          ) : (
            <PlaceholderArt />
          )}
          <span className={`status-pill status-${listing.status}`}>
            {STATUS_LABELS[listing.status]}
          </span>
          <span className="card-type">
            {listing.listing_type === "sale" ? "For sale" : "For rent"}
          </span>
        </div>
        <div className="card-body">
          <p className="card-price">{formatMoney(listing.list_price)}</p>
          <h3 className="card-title" id={`card-${listing.id}`}>
            <Link to={`/listings/${listing.id}`}>{listing.title}</Link>
          </h3>
          <p className="card-location">{placeOf(listing)}</p>
          <ul className="card-specs" aria-label="Key facts">
            {property.bedrooms != null && (
              <li>
                <Icon name="bed" />
                {property.bedrooms} bed
              </li>
            )}
            {property.bathrooms != null && (
              <li>
                <Icon name="bath" />
                {property.bathrooms} bath
              </li>
            )}
            {property.area && (
              <li>
                <Icon name="area" />
                {Number(property.area.value).toLocaleString("en-IN")}{" "}
                {property.area.unit === "sqft" ? "sq ft" : "sq m"}
              </li>
            )}
          </ul>
          <p className="card-foot">
            <span>{listing.listing_agent.full_name}</span>
            <span>{listing.organisation_name}</span>
          </p>
          {explanation && (
            <p className="card-match">{matchText(explanation, score)}</p>
          )}
        </div>
      </article>
    </li>
  );
}

const VIEW_KEY = "mls.listingView";

function rememberedView(): "grid" | "table" {
  try {
    return window.localStorage.getItem(VIEW_KEY) === "table" ? "table" : "grid";
  } catch {
    return "grid"; // storage can be blocked; the grid is the default
  }
}

const EMPTY_FILTERS = {
  // Ranked semantic search; when set, `q` and `sort` do not apply.
  describe: "",
  q: "",
  status: "",
  scope: "all",
  city: "",
  min_price: "",
  max_price: "",
  sort: "newest",
  // Set by "Search this area" on the map.
  min_lat: "",
  min_lon: "",
  max_lat: "",
  max_lon: "",
};

function toPath(filters: typeof EMPTY_FILTERS): string {
  const { describe, ...rest } = filters;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(rest)) {
    if (value.trim()) params.set(key, value.trim());
  }
  if (!describe.trim()) return `/listings?${params.toString()}`;
  params.delete("sort");
  params.set("q", describe.trim());
  return `/listings/search?${params.toString()}`;
}

export function Listings({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  // `draft` is what the form shows; `applied` is what the list was last searched with.
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const listings = useList<Listing | SearchHit>(
    toPath(applied),
    organisation.id,
  );
  const rows = useMemo(
    () =>
      listings.items.map((item) =>
        "explanation" in item
          ? item
          : { listing: item, explanation: null, score: null },
      ),
    [listings.items],
  );
  const note = rows.find((row) => row.explanation?.note)?.explanation?.note;

  const [showMap, setShowMap] = useState(false);
  const [view, setView] = useState(rememberedView);

  function choose(next: "grid" | "table") {
    setView(next);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      // not remembered across visits; nothing else depends on it
    }
  }
  const points = useMemo(
    () =>
      rows.flatMap(({ listing }) => {
        const location = listing.property.location;
        return location
          ? [
              {
                id: listing.id,
                lat: Number(location.latitude),
                lon: Number(location.longitude),
                label: listing.title,
                href: `/listings/${listing.id}`,
              },
            ]
          : [];
      }),
    [rows],
  );
  const inArea = applied.min_lat !== "";

  function searchArea(bounds: Bounds) {
    const area = {
      min_lat: bounds.min_lat.toFixed(6),
      min_lon: bounds.min_lon.toFixed(6),
      max_lat: bounds.max_lat.toFixed(6),
      max_lon: bounds.max_lon.toFixed(6),
    };
    setDraft((current) => ({ ...current, ...area }));
    setApplied((current) => ({ ...current, ...area }));
  }

  function anyArea() {
    const area = { min_lat: "", min_lon: "", max_lat: "", max_lon: "" };
    setDraft((current) => ({ ...current, ...area }));
    setApplied((current) => ({ ...current, ...area }));
  }

  const set = (key: keyof typeof EMPTY_FILTERS) => (value: string) =>
    setDraft((current) => ({ ...current, [key]: value }));

  function search(event: FormEvent) {
    event.preventDefault();
    setApplied(draft);
  }

  function reset() {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
  }

  const canWrite = organisation.my_permissions.includes("listing:write");

  return (
    <section aria-labelledby="listings-heading">
      <header className="page-head">
        <div>
          <p className="eyebrow">Inventory</p>
          <h2 id="listings-heading">Listings</h2>
          <p className="lede">
            Your organisation&apos;s listings and those shared across the
            network.
          </p>
        </div>
        {canWrite && (
          <div className="page-actions">
            <Link className="button-link" to="/listings/import">
              <Icon name="upload" />
              Import listings
            </Link>
            <Link className="button-link primary" to="/listings/new">
              <Icon name="plus" />
              New listing
            </Link>
          </div>
        )}
      </header>

      <form className="filters" onSubmit={search} aria-label="Filter listings">
        <div className="describe">
          <span className="label-row">
            <label htmlFor="describe-home">Describe the home</label>
            <AiTag>Semantic search</AiTag>
          </span>
          <input
            id="describe-home"
            type="search"
            placeholder="e.g. sea-facing flat with a balcony near the station"
            maxLength={500}
            value={draft.describe}
            onChange={(e) => set("describe")(e.target.value)}
          />
        </div>
        <label>
          Search
          <input
            type="search"
            placeholder="Title, locality or city"
            value={draft.q}
            onChange={(e) => set("q")(e.target.value)}
          />
        </label>
        <label>
          Status
          <select
            value={draft.status}
            onChange={(e) => set("status")(e.target.value)}
          >
            <option value="">Any</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Show
          <select
            value={draft.scope}
            onChange={(e) => set("scope")(e.target.value)}
          >
            <option value="all">All I can see</option>
            <option value="organisation">{organisation.name} only</option>
            <option value="network">Shared by other organisations</option>
          </select>
        </label>
        <label>
          City
          <input
            value={draft.city}
            onChange={(e) => set("city")(e.target.value)}
          />
        </label>
        <label>
          Min price
          <input
            type="number"
            min="0"
            inputMode="numeric"
            value={draft.min_price}
            onChange={(e) => set("min_price")(e.target.value)}
          />
        </label>
        <label>
          Max price
          <input
            type="number"
            min="0"
            inputMode="numeric"
            value={draft.max_price}
            onChange={(e) => set("max_price")(e.target.value)}
          />
        </label>
        <label>
          Sort
          <select
            value={draft.sort}
            onChange={(e) => set("sort")(e.target.value)}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="price_asc">Price, low to high</option>
            <option value="price_desc">Price, high to low</option>
          </select>
        </label>
        <div className="filter-actions">
          <button type="submit">Search</button>
          <button type="button" onClick={reset}>
            Clear filters
          </button>
        </div>
      </form>

      <div className="results-bar">
        <div>
          {!listings.loading && !listings.error && (
            <span>
              {rows.length}
              {listings.next ? "+" : ""}{" "}
              {rows.length === 1 ? "listing" : "listings"}
            </span>
          )}
          {inArea && (
            <>
              <span>Showing listings in the map area.</span>
              <button type="button" className="small" onClick={anyArea}>
                Any area
              </button>
            </>
          )}
        </div>
        <div>
          <div className="segmented" role="group" aria-label="Layout">
            <button
              type="button"
              aria-pressed={view === "grid"}
              onClick={() => choose("grid")}
            >
              <Icon name="grid" />
              Grid
            </button>
            <button
              type="button"
              aria-pressed={view === "table"}
              onClick={() => choose("table")}
            >
              <Icon name="table" />
              Table
            </button>
          </div>
          <button
            type="button"
            aria-pressed={showMap}
            onClick={() => setShowMap((shown) => !shown)}
          >
            <Icon name="map" />
            {showMap ? "Hide map" : "Show map"}
          </button>
        </div>
      </div>
      {showMap && (
        <>
          <MapView
            points={points}
            label="Map of the listings below"
            onSearchArea={searchArea}
          />
          {points.length < rows.length && (
            <p>
              {rows.length - points.length} of the listings below have no
              location and are not on the map.
            </p>
          )}
        </>
      )}
      {listings.loading && (
        <>
          <p className="visually-hidden" role="status">
            Loading…
          </p>
          <ul className="listing-grid" aria-hidden="true">
            {[0, 1, 2].map((n) => (
              <li key={n} style={{ "--i": n } as CSSProperties}>
                <div className="listing-card skeleton-card">
                  <div className="card-media skeleton" />
                  <div className="card-body">
                    <span
                      className="skeleton skeleton-line"
                      style={{ width: "45%" }}
                    />
                    <span
                      className="skeleton skeleton-line"
                      style={{ width: "80%" }}
                    />
                    <span
                      className="skeleton skeleton-line"
                      style={{ width: "60%" }}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {listings.error && <p role="alert">{listings.error}</p>}
      {!listings.loading && !listings.error && rows.length === 0 && (
        <div className="empty">
          <Icon name="grid" />
          <p className="empty-title">No listings match.</p>
          <p>Try fewer filters, or clear them to see everything.</p>
        </div>
      )}
      {applied.describe && rows.length > 0 && (
        <p>
          Best matches first.{" "}
          {note && <strong className="demo-note">{note}</strong>}
        </p>
      )}
      {rows.length > 0 && view === "grid" && (
        <ul className="listing-grid" aria-label="Listing results">
          {rows.map(({ listing, explanation, score }, index) => (
            <ListingCard
              key={listing.id}
              listing={listing}
              index={index}
              explanation={explanation}
              score={score}
            />
          ))}
        </ul>
      )}
      {rows.length > 0 && view === "table" && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Title</th>
                <th scope="col">Status</th>
                <th scope="col">Price</th>
                <th scope="col">For</th>
                <th scope="col">Location</th>
                <th scope="col">Beds</th>
                <th scope="col">Agent</th>
                <th scope="col">Organisation</th>
                {applied.describe && <th scope="col">Why it matched</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ listing, explanation, score }) => {
                return (
                  <tr key={listing.id}>
                    <th scope="row">
                      <span className="row-title">
                        {listing.cover_url ? (
                          <img
                            className="row-thumb"
                            src={listing.cover_url}
                            alt=""
                            loading="lazy"
                          />
                        ) : (
                          <span className="row-thumb" aria-hidden="true" />
                        )}
                        <Link to={`/listings/${listing.id}`}>
                          {listing.title}
                        </Link>
                      </span>
                    </th>
                    <td>
                      <span className={`status-pill status-${listing.status}`}>
                        {STATUS_LABELS[listing.status]}
                      </span>
                    </td>
                    <td>{formatMoney(listing.list_price)}</td>
                    <td>{listing.listing_type === "sale" ? "Sale" : "Rent"}</td>
                    <td>{placeOf(listing)}</td>
                    <td>{listing.property.bedrooms ?? "—"}</td>
                    <td>{listing.listing_agent.full_name}</td>
                    <td>{listing.organisation_name}</td>
                    {explanation && <td>{matchText(explanation, score)}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {listings.next && (
        <div className="actions">
          <button type="button" onClick={() => void listings.loadMore()}>
            Load more
          </button>
        </div>
      )}
    </section>
  );
}
