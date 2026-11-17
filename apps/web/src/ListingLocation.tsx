import { type FormEvent, Fragment, useEffect, useMemo, useState } from "react";

import { api, useAction } from "./api";
import type { components } from "./api-schema";
import { POLL_MS } from "./ListingMedia";
import type { Listing } from "./Listings";
import { MapView } from "./MapView";

type Property = Listing["property"];
type Location = NonNullable<Property["location"]>;
type Enrichment = components["schemas"]["EnrichmentItemOut"];

const SOURCE_TEXT: Record<Location["source"], string> = {
  demo: "demo geocoder (approximate centres of known areas and cities)",
  nominatim: "OpenStreetMap Nominatim",
  manual: "set by hand",
};
const PRECISION_TEXT: Record<Location["precision"], string> = {
  address: "the building",
  locality: "the area",
  city: "the city centre only",
};
const ZOOM: Record<Location["precision"], number> = {
  address: 16,
  locality: 14,
  city: 11,
};

const when = (iso: string) => new Date(iso).toLocaleDateString();

/** The property's point on a map, where it came from, and neighbourhood facts. */
export function ListingLocation({
  property: loaded,
  title,
  isOwn,
  canEdit,
}: {
  property: Property;
  title: string;
  /** Location lookups and enrichment are only for the owning organisation. */
  isOwn: boolean;
  canEdit: boolean;
}) {
  // Newer than `loaded` after a poll or a manual point; the parent remounts on reload.
  const [updated, setUpdated] = useState<Property | null>(null);
  const property = updated ?? loaded;
  const location = property.location;
  const pending = property.location_status === "pending";

  // Bumped after a failed poll, so polling goes on.
  const [failedPolls, setFailedPolls] = useState(0);
  useEffect(() => {
    if (!isOwn || !pending) return;
    const timer = setTimeout(() => {
      api<Property>(`/properties/${property.id}`)
        .then(setUpdated)
        .catch(() => setFailedPolls((n) => n + 1));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [isOwn, pending, property, failedPolls]);

  const [enrichment, setEnrichment] = useState<Enrichment[] | null>(null);
  useEffect(() => {
    if (!isOwn || pending) return;
    let cancelled = false;
    api<Enrichment[]>(`/properties/${property.id}/enrichment`)
      .then((items) => !cancelled && setEnrichment(items))
      .catch(() => !cancelled && setEnrichment(null));
    return () => {
      cancelled = true;
    };
  }, [isOwn, pending, property.id, location?.located_at]);

  const [editing, setEditing] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const save = useAction();

  const draftLat = parseFloat(lat);
  const draftLon = parseFloat(lon);
  const hasDraft = Number.isFinite(draftLat) && Number.isFinite(draftLon);
  const points = useMemo(() => {
    if (editing && hasDraft)
      return [
        { id: "draft", lat: draftLat, lon: draftLon, label: "New point" },
      ];
    if (location)
      return [
        {
          id: property.id,
          lat: Number(location.latitude),
          lon: Number(location.longitude),
          label: title,
        },
      ];
    return [];
  }, [editing, hasDraft, draftLat, draftLon, location, property.id, title]);

  function startEditing() {
    setLat(location?.latitude ?? "");
    setLon(location?.longitude ?? "");
    setEditing(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void save.run(async () => {
      const result = await api<Property>(
        `/properties/${property.id}/location`,
        {
          method: "PUT",
          body: { latitude: lat.trim(), longitude: lon.trim() },
        },
      );
      setUpdated(result);
      setEditing(false);
    });
  }

  return (
    <section aria-labelledby="location-heading">
      <h3 id="location-heading">Location</h3>
      {location ? (
        <p>
          {location.latitude}, {location.longitude}. Accurate to{" "}
          {PRECISION_TEXT[location.precision]}. Source:{" "}
          {SOURCE_TEXT[location.source]}, {when(location.located_at)}.
          {location.attribution && ` ${location.attribution}.`}
        </p>
      ) : pending ? (
        <p>Finding this address on the map…</p>
      ) : (
        <p>{property.location_error ?? "No location yet."}</p>
      )}

      {(points.length > 0 || editing) && (
        <MapView
          points={points}
          label={`Map of ${title}`}
          zoom={editing ? 15 : ZOOM[location?.precision ?? "city"]}
          onPick={
            editing
              ? (pickedLat, pickedLon) => {
                  setLat(pickedLat.toFixed(7));
                  setLon(pickedLon.toFixed(7));
                }
              : undefined
          }
        />
      )}

      {isOwn && canEdit && !editing && (
        <button type="button" onClick={startEditing}>
          Set the point by hand
        </button>
      )}
      {editing && (
        <form onSubmit={submit} aria-label="Set the point by hand">
          <p>
            Click the map or type the coordinates. A point set by hand is kept
            when the address changes.
          </p>
          <label>
            Latitude
            <input
              required
              inputMode="decimal"
              value={lat}
              onChange={(e) => setLat(e.target.value)}
            />
          </label>
          <label>
            Longitude
            <input
              required
              inputMode="decimal"
              value={lon}
              onChange={(e) => setLon(e.target.value)}
            />
          </label>
          {save.error && <p role="alert">{save.error}</p>}
          <button type="submit" disabled={save.busy}>
            Save point
          </button>
          <button type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </form>
      )}

      {enrichment && (
        <>
          <h4>Neighbourhood</h4>
          <dl>
            {enrichment.map((item) => (
              <Fragment key={item.key}>
                <dt>{item.label}</dt>
                <dd>
                  {item.value != null
                    ? `${item.value} (${item.source}${item.retrieved_at ? `, ${when(item.retrieved_at)}` : ""})`
                    : `Not available: ${item.reason}`}
                </dd>
              </Fragment>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}
