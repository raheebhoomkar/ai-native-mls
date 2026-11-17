import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { type CurrentOrganisation, useList } from "./api";
import type { components } from "./api-schema";

export type Listing = components["schemas"]["ListingOut"];
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

const EMPTY_FILTERS = {
  q: "",
  status: "",
  scope: "all",
  city: "",
  min_price: "",
  max_price: "",
  sort: "newest",
};

function toQuery(filters: typeof EMPTY_FILTERS): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value.trim()) params.set(key, value.trim());
  }
  return params.toString();
}

export function Listings({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  // `draft` is what the form shows; `applied` is what the list was last searched with.
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const listings = useList<Listing>(
    `/listings?${toQuery(applied)}`,
    organisation.id,
  );

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

  return (
    <section aria-labelledby="listings-heading">
      <h2 id="listings-heading">Listings</h2>
      {organisation.my_permissions.includes("listing:write") && (
        <p>
          <Link to="/listings/new">New listing</Link> ·{" "}
          <Link to="/listings/import">Import listings</Link>
        </p>
      )}

      <form className="filters" onSubmit={search} aria-label="Filter listings">
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

      {listings.loading && <p>Loading…</p>}
      {listings.error && <p role="alert">{listings.error}</p>}
      {!listings.loading && !listings.error && listings.items.length === 0 && (
        <p>No listings match.</p>
      )}
      {listings.items.length > 0 && (
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
              </tr>
            </thead>
            <tbody>
              {listings.items.map((listing) => {
                const address = listing.property.address;
                return (
                  <tr key={listing.id}>
                    <th scope="row">
                      <Link to={`/listings/${listing.id}`}>
                        {listing.title}
                      </Link>
                    </th>
                    <td>{STATUS_LABELS[listing.status]}</td>
                    <td>{formatMoney(listing.list_price)}</td>
                    <td>{listing.listing_type === "sale" ? "Sale" : "Rent"}</td>
                    <td>
                      {[address.locality, address.city]
                        .filter(Boolean)
                        .join(", ")}
                    </td>
                    <td>{listing.property.bedrooms ?? "—"}</td>
                    <td>{listing.listing_agent.full_name}</td>
                    <td>{listing.organisation_name}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {listings.next && (
        <button type="button" onClick={() => void listings.loadMore()}>
          Load more
        </button>
      )}
    </section>
  );
}
