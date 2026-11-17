"""Vector stores: one interface, Postgres (default) and Qdrant adapters.

Callers pass `candidate_ids`: the listings the SQL filter and visibility rule already allow.
A store only ranks them. The Qdrant query also filters by tenant and visibility payload, so a
store bug alone can never widen what a caller sees.
"""

import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai.providers import MalformedOutput, ProviderUnavailable
from app.modules.search.models import ListingVector


@dataclass(frozen=True)
class VectorPoint:
    listing_id: UUID
    organisation_id: UUID
    visibility: str
    status: str
    vector: list[float]


class VectorStore(Protocol):
    def upsert(self, session: Session, model_key: str, point: VectorPoint) -> None: ...

    def delete(self, session: Session, listing_id: UUID) -> None: ...

    def query(
        self,
        session: Session,
        model_key: str,
        vector: list[float],
        *,
        organisation_id: UUID,
        network_statuses: Sequence[str],
        candidate_ids: Sequence[UUID],
        limit: int,
    ) -> list[tuple[UUID, float]]:
        """Best first: (listing_id, cosine similarity)."""
        ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


class PostgresVectorStore:
    """Vectors in a table, scored in Python.

    shortcut: scores every candidate in Python; fine to ~20k listings, then use Qdrant or pgvector.
    """

    def upsert(self, session: Session, model_key: str, point: VectorPoint) -> None:
        values = {
            "listing_id": point.listing_id,
            "organisation_id": point.organisation_id,
            "model_key": model_key,
            "vector": point.vector,
        }
        session.execute(
            insert(ListingVector)
            .values(**values)
            .on_conflict_do_update(index_elements=["listing_id"], set_=values)
        )

    def delete(self, session: Session, listing_id: UUID) -> None:
        session.execute(delete(ListingVector).where(ListingVector.listing_id == listing_id))

    def query(
        self,
        session: Session,
        model_key: str,
        vector: list[float],
        *,
        organisation_id: UUID,
        network_statuses: Sequence[str],
        candidate_ids: Sequence[UUID],
        limit: int,
    ) -> list[tuple[UUID, float]]:
        if not candidate_ids:
            return []
        rows = session.execute(
            select(ListingVector.listing_id, ListingVector.vector).where(
                ListingVector.model_key == model_key,
                ListingVector.listing_id.in_(candidate_ids),
            )
        ).all()
        scored = [(listing_id, cosine(vector, stored)) for listing_id, stored in rows]
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]


# (method, url, headers, body) -> (status, body)
QdrantTransport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


def urllib_qdrant_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    # Plain http only for a Qdrant on this machine (docker compose); anything else needs https.
    if not (url.startswith("https://") or re.match(r"http://(localhost|127\.0\.0\.1)[:/]", url)):
        raise ValueError("Qdrant must be reached over https (or http on localhost).")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # scheme checked above
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def collection_name(model_key: str) -> str:
    return "listings-" + re.sub(r"[^A-Za-z0-9_-]", "-", model_key)


class QdrantVectorStore:
    """Qdrant over its REST API. One collection per embedder model key."""

    def __init__(
        self, url: str, api_key: str | None, transport: QdrantTransport = urllib_qdrant_transport
    ) -> None:
        self._url = url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["api-key"] = api_key
        self._transport = transport
        self._ready: set[str] = set()

    def _call(self, method: str, path: str, body: object = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        try:
            status, raw = self._transport(method, self._url + path, self._headers, data)
        except OSError as error:
            raise ProviderUnavailable(f"Qdrant could not be reached: {error}") from error
        if status >= 500:
            raise ProviderUnavailable(f"Qdrant answered {status}.")
        try:
            return status, json.loads(raw) if raw else None
        except ValueError as error:
            raise MalformedOutput("Qdrant answer could not be read.") from error

    def _ok(self, method: str, path: str, body: object = None) -> Any:
        status, answer = self._call(method, path, body)
        if status != 200:
            raise MalformedOutput(f"Qdrant refused {method} {path}: {status} {answer}")
        return answer

    def _ensure(self, name: str, dimension: int) -> None:
        if name in self._ready:
            return
        if not self._ok("GET", f"/collections/{name}/exists")["result"]["exists"]:
            self._ok(
                "PUT",
                f"/collections/{name}",
                {"vectors": {"size": dimension, "distance": "Cosine"}},
            )
            for field in ("organisation_id", "visibility", "status"):
                self._ok(
                    "PUT",
                    f"/collections/{name}/index?wait=true",
                    {"field_name": field, "field_schema": "keyword"},
                )
        self._ready.add(name)

    def upsert(self, session: Session, model_key: str, point: VectorPoint) -> None:
        name = collection_name(model_key)
        self._ensure(name, len(point.vector))
        payload = {
            "organisation_id": str(point.organisation_id),
            "visibility": point.visibility,
            "status": point.status,
        }
        body = {
            "points": [{"id": str(point.listing_id), "vector": point.vector, "payload": payload}]
        }
        self._ok("PUT", f"/collections/{name}/points?wait=true", body)

    def delete(self, session: Session, listing_id: UUID) -> None:
        # The listing may sit in a collection of an older model too; remove it everywhere.
        for collection in self._ok("GET", "/collections")["result"]["collections"]:
            if collection["name"].startswith("listings-"):
                self._ok(
                    "POST",
                    f"/collections/{collection['name']}/points/delete?wait=true",
                    {"points": [str(listing_id)]},
                )

    def query(
        self,
        session: Session,
        model_key: str,
        vector: list[float],
        *,
        organisation_id: UUID,
        network_statuses: Sequence[str],
        candidate_ids: Sequence[UUID],
        limit: int,
    ) -> list[tuple[UUID, float]]:
        if not candidate_ids:
            return []
        body = {
            "query": vector,
            "limit": limit,
            "filter": {
                "must": [{"has_id": [str(item) for item in candidate_ids]}],
                "should": [
                    {"key": "organisation_id", "match": {"value": str(organisation_id)}},
                    {
                        "must": [
                            {"key": "visibility", "match": {"value": "network"}},
                            {"key": "status", "match": {"any": list(network_statuses)}},
                        ]
                    },
                ],
            },
        }
        status, answer = self._call(
            "POST", f"/collections/{collection_name(model_key)}/points/query", body
        )
        if status == 404:
            return []  # nothing indexed with this model yet
        if status != 200:
            raise MalformedOutput(f"Qdrant refused the query: {status} {answer}")
        return [(UUID(str(p["id"])), float(p["score"])) for p in answer["result"]["points"]]


def get_vector_store() -> VectorStore:
    settings = get_settings()
    if settings.vector_store == "qdrant":
        key = settings.qdrant_api_key
        return QdrantVectorStore(settings.qdrant_url, key.get_secret_value() if key else None)
    return PostgresVectorStore()
