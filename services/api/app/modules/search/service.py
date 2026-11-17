"""Semantic listing search: the re-index job fed by the outbox, and hybrid search.

Hybrid: the normal listing filters and visibility rule pick the candidates in SQL; the
vector store only ranks those candidates.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.ai.providers import ProviderError
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.listings.models import Listing, Property
from app.modules.listings.schemas import ListingFilters
from app.modules.organisations.deps import TenantContext
from app.modules.outbox import service as outbox
from app.modules.search.embedder import get_embedder
from app.modules.search.vector_store import VectorPoint, get_vector_store

# Listings in these states leave the index; archived ones too.
UNSEARCHABLE = ("withdrawn", "expired")
# shortcut: ranks at most this many filter matches (newest first); add store-side filtering
# (Qdrant payload filters for every listing filter) if an organisation outgrows it.
MAX_CANDIDATES = 5000

outbox.subscribe("listing.changed", "search.reindex")
outbox.subscribe("property.changed", "search.reindex")


def listing_text(listing: Listing, prop: Property) -> str:
    place = ", ".join(part for part in (prop.locality, prop.city) if part)
    rooms = f"{prop.bedrooms} BHK " if prop.bedrooms else ""
    kind = "for sale" if listing.listing_type == "sale" else "to let"
    lines = [listing.title, f"{rooms}{prop.property_type} {kind} in {place}", listing.remarks or ""]
    return "\n".join(line for line in lines if line)


def index_listing(session: Session, listing_id: UUID) -> None:
    """Idempotent: puts the listing's current text in the index, or removes it."""
    store = get_vector_store()
    listing = session.get(Listing, listing_id)
    if listing is None or listing.archived_at is not None or listing.status in UNSEARCHABLE:
        store.delete(session, listing_id)
        return
    prop = session.get_one(Property, listing.property_id)
    # shortcut: embeds again on every change, even a price edit; cache by text hash if the
    # embedder's rate limit starts to bite.
    embeddings = get_embedder().embed([listing_text(listing, prop)], "document")
    store.upsert(
        session,
        embeddings.model_key,
        VectorPoint(
            listing_id=listing.id,
            organisation_id=listing.organisation_id,
            visibility=listing.visibility,
            status=listing.status,
            vector=embeddings.vectors[0],
        ),
    )


@jobs.handler("search.reindex")
def reindex(session: Session, job: Job) -> None:
    subject_id = UUID(job.payload["subject_id"])
    if job.payload["subject_type"] == "property":
        ids = list(session.scalars(select(Listing.id).where(Listing.property_id == subject_id)))
    else:
        ids = [subject_id]
    for listing_id in ids:
        index_listing(session, listing_id)


def enqueue_reindex(session: Session, listing_ids: Sequence[UUID]) -> None:
    """For backfills and embedder changes; the worker does the embedding."""
    rows = session.execute(
        select(Listing.id, Listing.organisation_id).where(Listing.id.in_(listing_ids))
    )
    for listing_id, organisation_id in rows:
        jobs.enqueue(
            session,
            "search.reindex",
            {"subject_type": "listing", "subject_id": str(listing_id)},
            organisation_id=organisation_id,
        )


_WORD = re.compile(r"\w+")
# Not worth showing as a reason for a match.
_STOPWORDS = {"and", "at", "for", "in", "is", "of", "on", "or", "the", "to", "with"}


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.casefold()) if len(w) > 1 and w not in _STOPWORDS}


@dataclass(frozen=True)
class Hit:
    listing: Listing
    score: float
    matched_words: list[str]


@dataclass(frozen=True)
class Results:
    hits: list[Hit]
    source: str
    model: str


def search(
    session: Session, ctx: TenantContext, filters: ListingFilters, text: str, limit: int
) -> Results:
    candidates = filtered_ids(session, ctx, filters)
    try:
        query = get_embedder().embed([text], "query")
        ranked = get_vector_store().query(
            session,
            query.model_key,
            query.vectors[0],
            organisation_id=ctx.organisation_id,
            network_statuses=listings.NETWORK_STATUSES,
            candidate_ids=candidates,
            limit=limit,
        )
    except ProviderError as error:
        raise AppError(
            503, "search_unavailable", f"Search is unavailable right now: {error}"
        ) from error
    # Only ids from the SQL candidates count, whatever the store returned.
    allowed = set(candidates)
    ranked = [(listing_id, score) for listing_id, score in ranked if listing_id in allowed]
    rows = {
        item.id: item
        for item in session.scalars(select(Listing).where(Listing.id.in_([i for i, _ in ranked])))
    }
    properties = listings.get_properties(session, [item.property_id for item in rows.values()])
    wanted = words(text)
    hits = []
    for listing_id, score in ranked:
        listing = rows[listing_id]
        found = wanted & words(listing_text(listing, properties[listing.property_id]))
        hits.append(Hit(listing, round(score, 4), sorted(found)))
    return Results(hits, query.source, query.model)


def filtered_ids(session: Session, ctx: TenantContext, filters: ListingFilters) -> list[UUID]:
    stmt = (
        listings.filtered_listings(ctx, filters.model_copy(update={"q": None}))
        .with_only_columns(Listing.id)
        .order_by(Listing.created_at.desc())
        .limit(MAX_CANDIDATES)
    )
    return list(session.scalars(stmt))
