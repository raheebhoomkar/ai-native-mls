from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OutboxEvent(Base):
    """Something changed. Written in the same transaction as the change, so an event exists
    if and only if the change committed. Consumers (search re-index now; webhooks and
    notifications later) get a job per event; see app/modules/outbox/service.py.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_subject", "subject_type", "subject_id"),
        Index("ix_outbox_events_organisation_created", "organisation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(50))
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[UUID]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
