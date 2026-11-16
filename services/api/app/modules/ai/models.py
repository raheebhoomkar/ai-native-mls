from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

RUN_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed")


class AgentRun(Base):
    """One AI task on one listing, kept as the audit record of what the model was asked and said.

    The `jobs` row runs the work; this row records it (INSTRUCTIONS.md 3.5). Inputs are
    references (media asset ID and SHA-256), never copies of the files.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(one_of("status", RUN_STATUSES), name="ck_agent_runs_status"),
        CheckConstraint("attempts >= 0", name="ck_agent_runs_attempts"),
        Index("ix_agent_runs_listing_created", "listing_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"))
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"))
    agent: Mapped[str] = mapped_column(String(50))
    agent_version: Mapped[str] = mapped_column(String(20))
    # Filled in when the provider answers; "demo" marks output that no model produced.
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(80))
    inputs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Validated `Extraction` (see schemas.py); never written unless it passed validation.
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
