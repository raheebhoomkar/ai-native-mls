import { type ChangeEvent, useEffect, useState } from "react";
import { Link } from "react-router";

import { api, describeError, useAction } from "./api";
import type { components } from "./api-schema";

type Field = components["schemas"]["FieldOut"];
type Preview = components["schemas"]["PreviewOut"];
type Problem = components["schemas"]["ProblemOut"];
type Imported = components["schemas"]["ImportOut"];
type ImportSource = components["schemas"]["ImportSourceOut"];

const SHOWN_VALUES = [
  "title",
  "property_type",
  "listing_type",
  "list_price",
  "city",
];

function shown(name: string, value: string | undefined) {
  if (value === undefined) return "—";
  // Indian digit grouping: 1,25,00,000.
  return name === "list_price"
    ? Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })
    : value;
}

/** Choose a CSV, preview how it maps and what is wrong, then import it as private drafts. */
export function ListingImport() {
  const [fields, setFields] = useState<Field[]>([]);
  const [file, setFile] = useState<{ name: string; content: string } | null>(
    null,
  );
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<Imported | null>(null);
  const { run, busy, error } = useAction();

  useEffect(() => {
    api<Field[]>("/imports/fields").then(setFields, () => setFields([]));
  }, []);

  const label = (name: string) =>
    fields.find((f) => f.name === name)?.label ?? name;

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0];
    event.target.value = ""; // choosing the same, fixed file again still triggers a preview
    if (!chosen) return;
    setPreview(null);
    setResult(null);
    run(async () => {
      const content = await chosen.text();
      setFile({ name: chosen.name, content });
      setPreview(
        await api<Preview>("/imports/preview", {
          method: "POST",
          body: { filename: chosen.name, content },
        }),
      );
    });
  }

  function importFile() {
    if (!file) return;
    run(async () => {
      setResult(
        await api<Imported>("/imports", {
          method: "POST",
          body: { filename: file.name, content: file.content },
        }),
      );
      setPreview(null);
    });
  }

  function problemText(problem: Problem) {
    const where =
      problem.field === "row" || problem.field === "file"
        ? ""
        : problem.column && problem.column !== label(problem.field)
          ? `${label(problem.field)} (column "${problem.column}"): `
          : `${label(problem.field)}: `;
    return where + problem.message;
  }

  const badRows = preview?.rows.filter((row) => row.errors.length > 0) ?? [];
  const ignored = preview?.columns.filter((c) => !c.field) ?? [];

  return (
    <section aria-labelledby="import-heading">
      <p>
        <Link to="/listings">← Listings</Link>
      </p>
      <h2 id="import-heading">Import listings</h2>
      <p>
        Choose a CSV file with one listing per row and a header row. Nothing is
        saved until you import. Every row becomes a private draft listing with
        you as the listing agent; nothing is shared or published.
      </p>
      <label htmlFor="import-file">CSV file</label>{" "}
      <input
        id="import-file"
        type="file"
        accept=".csv,text/csv"
        disabled={busy}
        onChange={choose}
      />
      {busy && <p>Working…</p>}
      {error && <p role="alert">{error}</p>}
      {result && (
        <div className="notice" role="status">
          <p>
            Imported {result.listings.length} listing
            {result.listings.length === 1 ? "" : "s"} from {result.filename} as
            private drafts.
          </p>
          <ul>
            {result.listings.map((item) => (
              <li key={item.listing_id}>
                Row {item.row_number}:{" "}
                <Link to={`/listings/${item.listing_id}`}>{item.title}</Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {preview && file && (
        <section aria-labelledby="preview-heading">
          <h3 id="preview-heading">Preview of {file.name}</h3>
          {preview.errors.length > 0 && (
            <div role="alert">
              <p>This file cannot be imported:</p>
              <ul>
                {preview.errors.map((problem, i) => (
                  <li key={i}>{problemText(problem)}</li>
                ))}
              </ul>
            </div>
          )}

          <p>
            Recognised columns:{" "}
            {preview.columns
              .filter((c) => c.field)
              .map((c) =>
                c.header.toLowerCase() === label(c.field!).toLowerCase()
                  ? c.header
                  : `${c.header} (as ${label(c.field!)})`,
              )
              .join(", ")}
            .
          </p>
          {ignored.length > 0 && (
            <p>
              Not recognised, so not imported:{" "}
              {ignored.map((c) => c.header || "(no header)").join(", ")}.
            </p>
          )}

          {preview.rows.length > 0 && (
            <>
              <p role="status">
                {badRows.length === 0
                  ? `All ${preview.rows.length} rows are ready to import.`
                  : `${badRows.length} of ${preview.rows.length} rows have problems. Fix them in the file and choose it again; nothing is imported until every row is valid.`}
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Row</th>
                      {SHOWN_VALUES.map((name) => (
                        <th key={name}>{label(name)}</th>
                      ))}
                      <th>Problems</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row) => (
                      <tr key={row.number}>
                        <td>{row.number}</td>
                        {SHOWN_VALUES.map((name) => (
                          <td key={name}>{shown(name, row.values[name])}</td>
                        ))}
                        <td className="import-problems">
                          {row.errors.length === 0 ? (
                            "None"
                          ) : (
                            <ul>
                              {row.errors.map((problem, i) => (
                                <li key={i}>{problemText(problem)}</li>
                              ))}
                            </ul>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {preview.ready && (
            <div className="actions">
              <button type="button" disabled={busy} onClick={importFile}>
                Import {preview.rows.length} listing
                {preview.rows.length === 1 ? "" : "s"}
              </button>
            </div>
          )}
        </section>
      )}
      {fields.length > 0 && <FieldReference fields={fields} />}
    </section>
  );
}

function FieldReference({ fields }: { fields: Field[] }) {
  const template =
    "data:text/csv;charset=utf-8," +
    encodeURIComponent(fields.map((f) => f.label).join(",") + "\n");

  return (
    <details>
      <summary>Fields and accepted column names</summary>
      <p>
        Column names ignore case, spaces and punctuation. RESO names are given
        where the RESO Data Dictionary has a close field; this is alignment, not
        a claim of RESO conformance.{" "}
        <a href={template} download="listing-import-template.csv">
          Download a template
        </a>
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Required</th>
              <th>RESO name</th>
              <th>Accepted column names</th>
              <th>Values</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr key={field.name}>
                <td>{field.label}</td>
                <td>{field.required ? "Yes" : "No"}</td>
                <td>{field.reso_name ?? "—"}</td>
                <td className="wrap">{field.accepted_headers.join(", ")}</td>
                <td className="wrap">{field.help}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** "Imported from" on the listing page; renders nothing for a listing made by hand. */
export function ImportSourceDetails({ listingId }: { listingId: string }) {
  const [source, setSource] = useState<ImportSource | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<ImportSource | null>(`/listings/${listingId}/import-source`).then(
      (found) => !cancelled && setSource(found),
      (caught) => !cancelled && setError(describeError(caught)),
    );
    return () => {
      cancelled = true;
    };
  }, [listingId]);

  if (error)
    return (
      <>
        <dt>Imported from</dt>
        <dd role="alert">{error}</dd>
      </>
    );
  if (!source) return null;
  return (
    <>
      <dt>Imported from</dt>
      <dd>
        {source.filename}, row {source.row_number}
        {source.external_id && ` (Listing ID ${source.external_id})`}, on{" "}
        {new Date(source.imported_at).toLocaleString()}
        <details>
          <summary>Original values</summary>
          <ul>
            {Object.entries(source.source).map(([header, value]) => (
              <li key={header}>
                {header}: {value}
              </li>
            ))}
          </ul>
        </details>
      </dd>
    </>
  );
}
