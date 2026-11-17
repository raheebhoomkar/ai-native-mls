import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api, describeError, type CurrentOrganisation } from "./api";
import type { components } from "./api-schema";
import { FindingFacts, reviewText } from "./ListingCompliance";

type Item = components["schemas"]["ComplianceQueueItemOut"];

/** Findings waiting for a reviewer in the organisation; decisions are made on the listing. */
export function ComplianceQueue({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Item[]>("/compliance/queue")
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch((caught) => {
        if (!cancelled) setError(describeError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [organisation.id]);

  return (
    <section aria-labelledby="queue-heading">
      <h2 id="queue-heading">Policy review queue</h2>
      <p>
        Findings from policy checks of {organisation.name}&apos;s listings that
        wait for a decision or an appeal ruling, oldest first. Your own listings
        are left out: someone else reviews them. A finding is decision support,
        not a legal judgement.
      </p>
      {error && <p role="alert">{error}</p>}
      {!items && !error && <p className="loading">Loading…</p>}
      {items?.length === 0 && <p>Nothing is waiting for review.</p>}
      {items && items.length > 0 && (
        <ol className="finding-list">
          {items.map((item) => (
            <li key={`${item.scan_id}:${item.finding_index}`}>
              <p>
                <Link to={`/listings/${item.listing_id}`}>
                  {item.listing_title}
                </Link>{" "}
                <small>
                  waiting since{" "}
                  {new Date(item.waiting_since).toLocaleString("en-IN")}
                </small>
              </p>
              <q className="evidence">
                <mark>{item.finding.evidence}</mark>
              </q>
              <FindingFacts finding={item.finding} />
              <p className="decision">{reviewText(item.review)}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
