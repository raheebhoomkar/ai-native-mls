"""Semantic search (Module 8): outbox, re-index job, hybrid search, Qdrant adapter."""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.modules.ai.providers import ProviderUnavailable
from app.modules.jobs.models import Job
from app.modules.outbox import service as outbox
from app.modules.outbox.models import OutboxEvent
from app.modules.search import service as search_service
from app.modules.search.models import ListingVector
from app.modules.search.vector_store import QdrantVectorStore, VectorPoint, collection_name
from tests.test_listings import LISTINGS, PROPERTIES, brokerage, move, new_listing, property_body
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here

SEARCH = f"{LISTINGS}/search"


def found(client: TestClient, q: str, **params: Any) -> list[dict[str, Any]]:
    response = client.get(SEARCH, params={"q": q, **params})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def titles(client: TestClient, q: str, **params: Any) -> list[str]:
    return [hit["listing"]["title"] for hit in found(client, q, **params)]


def vectors(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(ListingVector)) or 0


def test_listing_change_writes_event_and_job_in_the_same_transaction(
    db: Session, brokerage: Brokerage
) -> None:
    listing = new_listing(brokerage[2]["agent"])
    events = db.scalars(select(OutboxEvent).where(OutboxEvent.subject_id == UUID(listing["id"])))
    assert [event.kind for event in events] == ["listing.changed"]
    job = db.scalars(select(Job).where(Job.kind == "search.reindex")).one()
    assert job.payload["subject_id"] == listing["id"]


def test_rolled_back_change_leaves_no_event(db: Session, brokerage: Brokerage) -> None:
    org = brokerage[0]
    before = db.scalar(select(func.count()).select_from(OutboxEvent))
    nested = db.begin_nested()
    outbox.emit(
        db, "listing.changed", organisation_id=org.id, subject_type="listing", subject_id=uuid4()
    )
    nested.rollback()
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == before
    assert db.scalar(select(func.count()).where(Job.kind == "search.reindex")) == 0


def test_index_follows_the_listing_and_drops_withdrawn_and_archived(
    db: Session, brokerage: Brokerage
) -> None:
    agent = brokerage[2]["agent"]
    listing = new_listing(agent, title="Sea-facing flat")
    run_jobs(db)
    assert vectors(db) == 1
    assert titles(agent, "sea facing") == ["Sea-facing flat"]

    withdrawn = move(agent, listing, "withdrawn")
    run_jobs(db)
    assert vectors(db) == 0
    assert agent.delete(f"{LISTINGS}/{withdrawn['id']}").status_code == 204
    run_jobs(db)
    assert vectors(db) == 0
    assert titles(agent, "sea facing") == []


def test_property_change_reindexes_its_listings(db: Session, brokerage: Brokerage) -> None:
    agent = brokerage[2]["agent"]
    listing = new_listing(agent, title="Quiet flat")
    run_jobs(db)
    assert found(agent, "Bandra")[0]["explanation"]["matched_words"] == []
    prop = listing["property"]
    body = {k: prop[k] for k in ("property_type", "bedrooms", "bathrooms", "area")}
    body |= {"address": {**prop["address"], "locality": "Bandra"}, "version": prop["version"]}
    assert agent.put(f"{PROPERTIES}/{prop['id']}", json=body).status_code == 200
    run_jobs(db)
    assert found(agent, "Bandra")[0]["explanation"]["matched_words"] == ["bandra"]


def test_ranking_explanation_and_filters(db: Session, brokerage: Brokerage) -> None:
    agent = brokerage[2]["agent"]
    new_listing(agent, title="Sea-facing 3 BHK with balcony")
    new_listing(agent, title="Office space near the IT park")
    rented = property_body(property_type="villa")
    new_listing(agent, title="Sea-facing villa", property=rented)
    run_jobs(db)

    hits = found(agent, "sea facing balcony")
    assert hits[0]["listing"]["title"] == "Sea-facing 3 BHK with balcony"
    assert hits[0]["score"] > hits[-1]["score"]
    explanation = hits[0]["explanation"]
    assert set(explanation["matched_words"]) >= {"sea", "facing", "balcony"}
    assert (explanation["source"], explanation["model"]) == ("demo", "hashing-v1")
    assert "not meaning" in explanation["note"]
    assert explanation["filters"] == []

    villas = found(agent, "sea facing", property_type="villa")
    assert [hit["listing"]["title"] for hit in villas] == ["Sea-facing villa"]
    assert villas[0]["explanation"]["filters"] == ["property_type"]
    # The geo filters combine too: Powai is not within 1 km of Pune.
    assert titles(agent, "sea", near_lat=18.52, near_lon=73.85, radius_km=1) == []
    assert agent.get(SEARCH, params={"q": "  "}).status_code == 422


def test_other_organisations_private_listings_never_appear(
    db: Session, brokerage: Brokerage, make_user: Any, make_org: Any, login_as: Any
) -> None:
    clients = brokerage[2]
    outsider_user, outsider_broker = make_user("agent@b.example"), make_user("broker@b.example")
    make_org("Brokerage B", {outsider_user: "agent", outsider_broker: "broker"})
    outsider, broker_b = login_as(outsider_user), login_as(outsider_broker)
    new_listing(outsider, title="Private sea-facing flat")
    shared = new_listing(outsider, title="Shared sea-facing flat", visibility="network")
    shared_draft = new_listing(outsider, title="Shared draft sea-facing", visibility="network")
    move(broker_b, move(outsider, shared, "pending_review"), "active")
    run_jobs(db)

    assert titles(clients["agent"], "sea facing flat") == ["Shared sea-facing flat"]
    assert set(titles(outsider, "sea facing flat")) == {
        "Private sea-facing flat",
        "Shared sea-facing flat",
        shared_draft["title"],
    }
    assert titles(clients["agent"], "sea facing", scope="organisation") == []


def test_embedder_outage_is_503(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Down:
        def embed(self, texts: Any, purpose: Any) -> Any:
            raise ProviderUnavailable("Gemini could not be reached.")

    monkeypatch.setattr(search_service, "get_embedder", Down)
    response = brokerage[2]["agent"].get(SEARCH, params={"q": "flat"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "search_unavailable"


def test_backfill_enqueues_a_job_per_listing(db: Session, brokerage: Brokerage) -> None:
    listing = new_listing(brokerage[2]["agent"])
    run_jobs(db)
    db.execute(delete(ListingVector))
    search_service.enqueue_reindex(db, [UUID(listing["id"])])
    run_jobs(db)
    assert vectors(db) == 1


# --- Qdrant adapter, against a fake transport -------------------------------------------------


class FakeQdrant:
    def __init__(self, query_status: int = 200) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.query_status = query_status

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        path = url.removeprefix("https://q.example")
        self.calls.append((method, path, json.loads(body) if body else None))
        assert headers["api-key"] == "secret"
        if path.endswith("/exists"):
            return 200, b'{"result": {"exists": false}}'
        if path == "/collections":
            return 200, b'{"result": {"collections": [{"name": "listings-x"}, {"name": "other"}]}}'
        if path.endswith("/points/query"):
            if self.query_status != 200:
                return self.query_status, b'{"status": {"error": "Not found"}}'
            hit = {"result": {"points": [{"id": str(LISTING), "score": 0.9}]}}
            return 200, json.dumps(hit).encode()
        return 200, b'{"result": true}'


LISTING, ORG = uuid4(), uuid4()


def test_qdrant_creates_collection_and_upserts_with_tenant_payload(db: Session) -> None:
    fake = FakeQdrant()
    store = QdrantVectorStore("https://q.example/", "secret", fake)
    point = VectorPoint(LISTING, ORG, "network", "active", [0.1, 0.2, 0.3])
    store.upsert(db, "gemini/gemini-embedding-001/3", point)
    store.upsert(db, "gemini/gemini-embedding-001/3", point)
    name = collection_name("gemini/gemini-embedding-001/3")
    assert name == "listings-gemini-gemini-embedding-001-3"
    methods = [(method, path) for method, path, _ in fake.calls]
    assert methods.count(("PUT", f"/collections/{name}")) == 1  # created once
    assert fake.calls[1][2] == {"vectors": {"size": 3, "distance": "Cosine"}}
    upsert = fake.calls[-1][2]["points"][0]
    assert upsert["payload"] == {
        "organisation_id": str(ORG),
        "visibility": "network",
        "status": "active",
    }


def test_qdrant_query_filters_by_candidates_and_tenant(db: Session) -> None:
    fake = FakeQdrant()
    store = QdrantVectorStore("https://q.example", "secret", fake)
    kwargs: dict[str, Any] = {
        "organisation_id": ORG,
        "network_statuses": ("active",),
        "candidate_ids": [LISTING],
        "limit": 5,
    }
    assert store.query(db, "demo/hashing-v1/256", [1.0], **kwargs) == [(LISTING, 0.9)]
    query_filter = fake.calls[-1][2]["filter"]
    assert query_filter["must"] == [{"has_id": [str(LISTING)]}]
    assert {"key": "organisation_id", "match": {"value": str(ORG)}} in query_filter["should"]
    assert store.query(db, "demo/hashing-v1/256", [1.0], **{**kwargs, "candidate_ids": []}) == []
    missing = QdrantVectorStore("https://q.example", "secret", FakeQdrant(query_status=404))
    assert missing.query(db, "demo/hashing-v1/256", [1.0], **kwargs) == []


def test_qdrant_delete_reaches_every_listing_collection(db: Session) -> None:
    fake = FakeQdrant()
    QdrantVectorStore("https://q.example", "secret", fake).delete(db, LISTING)
    deletes = [path for method, path, _ in fake.calls if method == "POST"]
    assert deletes == ["/collections/listings-x/points/delete?wait=true"]


def test_qdrant_outage_is_retryable(db: Session) -> None:
    def down(*_: Any) -> tuple[int, bytes]:
        raise ConnectionRefusedError("refused")

    store = QdrantVectorStore("https://q.example", None, down)
    with pytest.raises(ProviderUnavailable):
        store.delete(db, LISTING)
