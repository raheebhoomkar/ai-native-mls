import { useEffect, useState } from "react";

import { api, describeError, useAction } from "./api";
import type { components } from "./api-schema";
import { formatMoney } from "./Listings";

type Valuation = components["schemas"]["ValuationOut"];

const percent = (share: number) => `${Math.round(share * 100)}%`;
const day = (iso: string) => new Date(iso).toLocaleDateString();

/** Estimate from comparable reported sales. Shown to the organisation that owns the listing. */
export function ListingValuation({ listingId }: { listingId: string }) {
  const [latest, setLatest] = useState<Valuation | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const action = useAction();

  useEffect(() => {
    let cancelled = false;
    api<Valuation[]>(`/listings/${listingId}/valuations`)
      .then((list) => {
        if (!cancelled) setLatest(list[0] ?? null);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [listingId]);

  function estimate() {
    void action.run(async () => {
      setLatest(
        await api<Valuation>(`/listings/${listingId}/valuations`, {
          method: "POST",
          body: {},
        }),
      );
    });
  }

  return (
    <section aria-labelledby="valuation-heading">
      <h3 id="valuation-heading">Valuation</h3>
      <p>
        <strong>
          {latest?.disclaimer ??
            "Not an appraisal and not a guaranteed sale price."}
        </strong>
      </p>
      <p>
        <button type="button" onClick={estimate} disabled={action.busy}>
          {action.busy
            ? "Estimating…"
            : latest
              ? "Estimate again"
              : "Estimate value"}
        </button>
      </p>
      {loadError && <p role="alert">{loadError}</p>}
      {action.error && <p role="alert">{action.error}</p>}
      {latest && <Result valuation={latest} />}
    </section>
  );
}

function Result({ valuation }: { valuation: Valuation }) {
  const { result, parameters, outcome } = valuation;
  const { estimate, simulation, asking } = result;
  const currency = result.currency;
  return (
    <>
      {estimate ? (
        <p>
          Estimated range <strong>{formatMoney(estimate.low)}</strong> to{" "}
          <strong>{formatMoney(estimate.high)}</strong>, middle{" "}
          {formatMoney(estimate.median)}. From {result.sample_size} reported
          sales closed between {result.data_from && day(result.data_from)} and{" "}
          {result.data_to && day(result.data_to)}
          {estimate.method === "price_per_sqft"
            ? `, by price per sq ft times ${estimate.subject_area_sqft} sq ft.`
            : ", by sale price (this property has no area)."}
        </p>
      ) : (
        <p role="status">{result.reason}</p>
      )}

      {outcome && (
        <p>
          Sold for {formatMoney(outcome.price)} on {day(outcome.at)}.
          {outcome.error_pct !== null &&
            ` The estimate's middle was ${percent(Math.abs(outcome.error_pct))} ${
              outcome.error_pct >= 0 ? "above" : "below"
            } it, ${outcome.within_range ? "inside" : "outside"} the range.`}
        </p>
      )}

      <h4>Days on market</h4>
      {simulation.available ? (
        <p>
          In {simulation.runs} simulated runs based on {simulation.samples} past
          sales, half sold within {simulation.days_p50} days (one in ten by{" "}
          {simulation.days_p10}, nine in ten by {simulation.days_p90}). Sold
          within 30, 60 and 90 days:{" "}
          {["30", "60", "90"]
            .map((d) => percent(simulation.sold_within?.[d] ?? 0))
            .join(", ")}{" "}
          of runs. A scenario, not a forecast.
        </p>
      ) : (
        <p>Not available. {simulation.reason}</p>
      )}
      <p>{result.offers_reason}</p>

      {asking && (
        <p>
          Asking prices of {asking.count} active comparable listing
          {asking.count === 1 ? "" : "s"}, not sale prices and not used above:{" "}
          {formatMoney({ amount: asking.low, currency })} to{" "}
          {formatMoney({ amount: asking.high, currency })}
          {asking.basis === "price_per_sqft" ? " per sq ft" : ""}.
        </p>
      )}

      {result.comps.length > 0 && (
        <div className="table-scroll">
          <table>
            <caption>Comparable sales. {result.comps[0]!.price_source}</caption>
            <thead>
              <tr>
                <th scope="col">Listing</th>
                <th scope="col">Sold for</th>
                <th scope="col">Closed</th>
                <th scope="col">Days on market</th>
                <th scope="col">Distance</th>
                <th scope="col">Area</th>
                <th scope="col">Per sq ft</th>
                <th scope="col">Organisation</th>
              </tr>
            </thead>
            <tbody>
              {result.comps.map((comp) => (
                <tr key={comp.listing_id}>
                  <th scope="row">{comp.title}</th>
                  <td>{formatMoney(comp.closed_price)}</td>
                  <td>{day(comp.closed_on)}</td>
                  <td>{comp.days_on_market ?? "—"}</td>
                  <td>
                    {comp.distance_km === null ? "—" : `${comp.distance_km} km`}
                  </td>
                  <td>{comp.area_sqft ? `${comp.area_sqft} sq ft` : "—"}</td>
                  <td>
                    {comp.price_per_sqft
                      ? formatMoney({ amount: comp.price_per_sqft, currency })
                      : "—"}
                  </td>
                  <td>{comp.organisation_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <details>
        <summary>Assumptions</summary>
        <ul>
          {result.assumptions.map((line) => (
            <li key={line}>{line}</li>
          ))}
          <li>
            Model {valuation.model_version}, simulation{" "}
            {valuation.simulation_version}, seed {parameters.seed}. Made{" "}
            {new Date(valuation.created_at).toLocaleString()}.
          </li>
        </ul>
      </details>
    </>
  );
}
