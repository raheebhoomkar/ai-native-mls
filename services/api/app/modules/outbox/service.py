"""Transactional outbox.

    outbox.subscribe("listing.changed", "search.reindex")   # at import time, by the consumer
    outbox.emit(session, "listing.changed", organisation_id=..., subject_type="listing",
                subject_id=listing.id)                       # in the changing transaction

Each subscriber gets its own job (payload: event_id, kind, subject_type, subject_id), so one
consumer failing or retrying never holds up another. Job handlers must be idempotent.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.jobs import service as jobs
from app.modules.outbox.models import OutboxEvent

_subscribers: dict[str, list[str]] = {}


def subscribe(event_kind: str, job_kind: str) -> None:
    targets = _subscribers.setdefault(event_kind, [])
    if job_kind not in targets:
        targets.append(job_kind)


def emit(
    session: Session,
    kind: str,
    *,
    organisation_id: UUID,
    subject_type: str,
    subject_id: UUID,
    payload: dict[str, Any] | None = None,
) -> OutboxEvent:
    event = OutboxEvent(
        kind=kind,
        organisation_id=organisation_id,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    for job_kind in _subscribers.get(kind, ()):
        jobs.enqueue(
            session,
            job_kind,
            {
                "event_id": str(event.id),
                "kind": kind,
                "subject_type": subject_type,
                "subject_id": str(subject_id),
            },
            organisation_id=organisation_id,
        )
    return event
