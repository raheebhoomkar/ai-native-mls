from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditEvent(Base):
    """Append-only record of a sensitive action. Rows are never updated."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_organisation_occurred", "organisation_id", "occurred_at"),
        Index("ix_audit_events_action_occurred", "action", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    organisation_id: Mapped[UUID | None] = mapped_column(ForeignKey("organisations.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(320))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    request_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
