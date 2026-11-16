/** Create a listing (with a new or existing property) and edit a listing and its property. */

import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  api,
  ApiError,
  type CurrentOrganisation,
  describeError,
  useAction,
  useList,
} from "./api";
import type { components } from "./api-schema";
import type { Listing } from "./Listings";

type Property = components["schemas"]["PropertyOut"];

// Form state is all strings, as inputs hold them; converted when sent.
const NEW_PROPERTY = {
  property_type: "apartment",
  line1: "",
  line2: "",
  locality: "",
  city: "",
  state: "",
  postal_code: "",
  country: "IN",
  bedrooms: "",
  bathrooms: "",
  area_value: "",
  area_unit: "sqft",
  year_built: "",
};
type PropertyForm = typeof NEW_PROPERTY;

const NEW_LISTING = {
  title: "",
  listing_type: "sale",
  amount: "",
  currency: "INR",
  visibility: "private",
  expires_on: "",
  remarks: "",
};
type ListingFormState = typeof NEW_LISTING;

const text = (value: string) => value.trim() || null;
const whole = (value: string) => (value === "" ? null : Number(value));

function propertyBody(form: PropertyForm) {
  return {
    property_type: form.property_type,
    address: {
      line1: form.line1,
      line2: text(form.line2),
      locality: text(form.locality),
      city: form.city,
      state: text(form.state),
      postal_code: text(form.postal_code),
      country: form.country.trim().toUpperCase(),
    },
    bedrooms: whole(form.bedrooms),
    bathrooms: whole(form.bathrooms),
    // Sent as a string so the exact decimal the user typed is stored.
    area: form.area_value
      ? { value: form.area_value, unit: form.area_unit }
      : null,
    year_built: whole(form.year_built),
  };
}

function listingBody(form: ListingFormState) {
  return {
    title: form.title,
    listing_type: form.listing_type,
    list_price: {
      amount: form.amount,
      currency: form.currency.trim().toUpperCase(),
    },
    visibility: form.visibility,
    expires_on: form.expires_on || null,
    remarks: text(form.remarks),
  };
}

function fromProperty(property: Property): PropertyForm {
  const a = property.address;
  return {
    property_type: property.property_type,
    line1: a.line1,
    line2: a.line2 ?? "",
    locality: a.locality ?? "",
    city: a.city,
    state: a.state ?? "",
    postal_code: a.postal_code ?? "",
    country: a.country,
    bedrooms: property.bedrooms?.toString() ?? "",
    bathrooms: property.bathrooms?.toString() ?? "",
    area_value: property.area?.value ?? "",
    area_unit: property.area?.unit ?? "sqft",
    year_built: property.year_built?.toString() ?? "",
  };
}

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label>
      {label}
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function PropertyFields({
  form,
  onChange,
}: {
  form: PropertyForm;
  onChange: (form: PropertyForm) => void;
}) {
  const bind = (key: keyof PropertyForm) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) =>
      onChange({ ...form, [key]: e.target.value }),
  });
  return (
    <div className="fields">
      <Field label="Property type">
        <select {...bind("property_type")}>
          <option value="apartment">Apartment</option>
          <option value="house">House</option>
          <option value="villa">Villa</option>
          <option value="plot">Plot</option>
          <option value="commercial">Commercial</option>
          <option value="other">Other</option>
        </select>
      </Field>
      <Field label="Address line 1">
        <input required maxLength={200} {...bind("line1")} />
      </Field>
      <Field label="Address line 2">
        <input maxLength={200} {...bind("line2")} />
      </Field>
      <Field label="Locality">
        <input maxLength={100} {...bind("locality")} />
      </Field>
      <Field label="City">
        <input required maxLength={100} {...bind("city")} />
      </Field>
      <Field label="State">
        <input maxLength={100} {...bind("state")} />
      </Field>
      <Field label="Postal code">
        <input maxLength={20} {...bind("postal_code")} />
      </Field>
      <Field label="Country" hint="Two-letter code, for example IN.">
        <input required minLength={2} maxLength={2} {...bind("country")} />
      </Field>
      <Field label="Bedrooms">
        <input type="number" min="0" max="100" step="1" {...bind("bedrooms")} />
      </Field>
      <Field label="Bathrooms">
        <input
          type="number"
          min="0"
          max="100"
          step="1"
          {...bind("bathrooms")}
        />
      </Field>
      <Field label="Area">
        <input type="number" min="0.01" step="0.01" {...bind("area_value")} />
      </Field>
      <Field label="Area unit">
        <select {...bind("area_unit")}>
          <option value="sqft">Square feet</option>
          <option value="sqm">Square metres</option>
        </select>
      </Field>
      <Field label="Year built">
        <input
          type="number"
          min="1600"
          max="2100"
          step="1"
          {...bind("year_built")}
        />
      </Field>
    </div>
  );
}

function ListingFields({
  form,
  onChange,
}: {
  form: ListingFormState;
  onChange: (form: ListingFormState) => void;
}) {
  const bind = (key: keyof ListingFormState) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) =>
      onChange({ ...form, [key]: e.target.value }),
  });
  return (
    <div className="fields">
      <Field label="Title">
        <input required maxLength={200} {...bind("title")} />
      </Field>
      <Field label="Listing for">
        <select {...bind("listing_type")}>
          <option value="sale">Sale</option>
          <option value="rent">Rent</option>
        </select>
      </Field>
      <Field label="List price">
        <input
          type="number"
          required
          min="0.01"
          step="0.01"
          {...bind("amount")}
        />
      </Field>
      <Field label="Currency" hint="Three-letter code, for example INR.">
        <input required minLength={3} maxLength={3} {...bind("currency")} />
      </Field>
      <Field
        label="Visibility"
        hint="Shared listings are shown to other organisations only while active, off market or sold."
      >
        <select {...bind("visibility")}>
          <option value="private">Private to this organisation</option>
          <option value="network">Shared with other organisations</option>
        </select>
      </Field>
      <Field label="Expires on">
        <input type="date" {...bind("expires_on")} />
      </Field>
      <Field label="Remarks">
        <textarea rows={4} maxLength={10000} {...bind("remarks")} />
      </Field>
    </div>
  );
}

function propertyLabel(property: Property) {
  const a = property.address;
  return [a.line1, a.locality, a.city].filter(Boolean).join(", ");
}

export function NewListing({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const navigate = useNavigate();
  const properties = useList<Property>(
    "/properties?limit=100",
    organisation.id,
  );
  const [propertyId, setPropertyId] = useState("new");
  const [property, setProperty] = useState(NEW_PROPERTY);
  const [listing, setListing] = useState(NEW_LISTING);
  // Kept if the listing step fails, so retrying does not create the property twice.
  const [createdPropertyId, setCreatedPropertyId] = useState<string | null>(
    null,
  );
  const save = useAction();

  function submit(event: FormEvent) {
    event.preventDefault();
    void save.run(async () => {
      let id = propertyId === "new" ? createdPropertyId : propertyId;
      if (id === null) {
        id = (
          await api<Property>("/properties", {
            method: "POST",
            body: propertyBody(property),
          })
        ).id;
        setCreatedPropertyId(id);
      }
      const created = await api<Listing>("/listings", {
        method: "POST",
        body: { property_id: id, ...listingBody(listing) },
      });
      navigate(`/listings/${created.id}`);
    });
  }

  return (
    <form
      className="wide"
      onSubmit={submit}
      aria-labelledby="new-listing-heading"
    >
      <p>
        <Link to="/listings">← Listings</Link>
      </p>
      <h2 id="new-listing-heading">New listing</h2>
      <p>
        The listing is created as a draft. Submit it for review from its page.
      </p>

      <h3>Property</h3>
      {properties.error && <p role="alert">{properties.error}</p>}
      <Field label="Which property is this listing for?">
        <select
          value={propertyId}
          disabled={createdPropertyId !== null}
          onChange={(e) => setPropertyId(e.target.value)}
        >
          <option value="new">A new property</option>
          {properties.items.map((item) => (
            <option key={item.id} value={item.id}>
              {propertyLabel(item)}
            </option>
          ))}
        </select>
      </Field>
      {propertyId === "new" && createdPropertyId === null && (
        <PropertyFields form={property} onChange={setProperty} />
      )}
      {createdPropertyId !== null && (
        <p role="status">
          The property was saved. Fix the listing details and save again.
        </p>
      )}

      <h3>Listing</h3>
      <ListingFields form={listing} onChange={setListing} />

      {save.error && <p role="alert">{save.error}</p>}
      <div className="actions">
        <button type="submit" disabled={save.busy}>
          {save.busy ? "Saving…" : "Create draft listing"}
        </button>
        <Link to="/listings">Cancel</Link>
      </div>
    </form>
  );
}

export function EditListing({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const { id } = useParams();
  const [loaded, setLoaded] = useState<Listing | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [listing, setListing] = useState(NEW_LISTING);
  const [property, setProperty] = useState(NEW_PROPERTY);
  const [saved, setSaved] = useState<"listing" | "property" | null>(null);
  const [conflict, setConflict] = useState(false);
  const [reloads, setReloads] = useState(0);
  const saveListing = useAction();
  const saveProperty = useAction();

  function show(fresh: Listing) {
    setLoaded(fresh);
    setListing({
      title: fresh.title,
      listing_type: fresh.listing_type,
      amount: fresh.list_price.amount,
      currency: fresh.list_price.currency,
      visibility: fresh.visibility,
      expires_on: fresh.expires_on ?? "",
      remarks: fresh.remarks ?? "",
    });
    setProperty(fromProperty(fresh.property));
  }

  useEffect(() => {
    let cancelled = false;
    api<Listing>(`/listings/${id}`)
      .then((fresh) => {
        if (cancelled) return;
        setConflict(false);
        show(fresh);
      })
      .catch((error) => !cancelled && setLoadError(describeError(error)));
    return () => {
      cancelled = true;
    };
  }, [id, organisation.id, reloads]);

  /** A version conflict needs a reload, which would discard typed changes, so the user decides. */
  async function guarded(action: () => Promise<void>) {
    try {
      await action();
    } catch (error) {
      if (error instanceof ApiError && error.code === "version_conflict") {
        setConflict(true);
        return;
      }
      throw error;
    }
  }

  if (loadError)
    return (
      <section>
        <p role="alert">{loadError}</p>
        <Link to="/listings">Back to listings</Link>
      </section>
    );
  if (!loaded) return <p>Loading…</p>;
  if (!loaded.can_edit || loaded.status === "sold")
    return (
      <section>
        <p>You cannot edit this listing.</p>
        <Link to={`/listings/${loaded.id}`}>Back to the listing</Link>
      </section>
    );

  function submitListing(event: FormEvent) {
    event.preventDefault();
    setSaved(null);
    void saveListing.run(() =>
      guarded(async () => {
        show(
          await api<Listing>(`/listings/${loaded!.id}`, {
            method: "PATCH",
            body: { version: loaded!.version, ...listingBody(listing) },
          }),
        );
        setSaved("listing");
      }),
    );
  }

  function submitProperty(event: FormEvent) {
    event.preventDefault();
    setSaved(null);
    void saveProperty.run(() =>
      guarded(async () => {
        const updated = await api<Property>(
          `/properties/${loaded!.property.id}`,
          {
            method: "PUT",
            body: {
              version: loaded!.property.version,
              ...propertyBody(property),
            },
          },
        );
        setLoaded({ ...loaded!, property: updated });
        setProperty(fromProperty(updated));
        setSaved("property");
      }),
    );
  }

  return (
    <section aria-labelledby="edit-listing-heading">
      <p>
        <Link to={`/listings/${loaded.id}`}>← Back to the listing</Link>
      </p>
      <h2 id="edit-listing-heading">Edit listing</h2>
      {conflict && (
        <div className="notice" role="alert">
          <p>
            Someone else changed this record, so your change was not saved.
            Reloading shows their version and discards what you typed.
          </p>
          <button type="button" onClick={() => setReloads((n) => n + 1)}>
            Reload and discard my changes
          </button>
        </div>
      )}

      <form
        className="wide"
        onSubmit={submitListing}
        aria-labelledby="edit-listing-details"
      >
        <h3 id="edit-listing-details">Listing details</h3>
        <ListingFields form={listing} onChange={setListing} />
        {saveListing.error && <p role="alert">{saveListing.error}</p>}
        {saved === "listing" && <p role="status">Listing saved.</p>}
        <div className="actions">
          <button type="submit" disabled={saveListing.busy}>
            Save listing
          </button>
        </div>
      </form>

      <form
        className="wide"
        onSubmit={submitProperty}
        aria-labelledby="edit-property-details"
      >
        <h3 id="edit-property-details">Property details</h3>
        <p>These belong to the property and show on every listing of it.</p>
        <PropertyFields form={property} onChange={setProperty} />
        {saveProperty.error && <p role="alert">{saveProperty.error}</p>}
        {saved === "property" && <p role="status">Property saved.</p>}
        <div className="actions">
          <button type="submit" disabled={saveProperty.busy}>
            Save property
          </button>
        </div>
      </form>
    </section>
  );
}
