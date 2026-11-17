from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

TASK_STATUSES: tuple[str, ...] = ("open", "closed")
DECISIONS: tuple[str, ...] = ("accepted", "edited", "rejected")


class ReviewTask(Base):
    """Something a person must check before it counts: AI suggestions, a redacted photo, a flag.

    Generic on purpose: the owning module names the subject and decides what a decision does.
    """

    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint(one_of("status", TASK_STATUSES), name="ck_review_tasks_status"),
        UniqueConstraint("subject_type", "subject_id", name="uq_review_tasks_subject"),
        Index("ix_review_tasks_organisation_status", "organisation_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewDecision(Base):
    """One person's decision on one item of a task. Never updated: one decision per item."""

    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint(one_of("decision", DECISIONS), name="ck_review_decisions_decision"),
        # NULLS NOT DISTINCT: a single-item task (item_key NULL) also gets one decision.
        UniqueConstraint(
            "task_id",
            "item_key",
            name="uq_review_decisions_item",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("review_tasks.id"))
    item_key: Mapped[str | None] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(20))
    # What was suggested and what the person kept (null when rejected).
    suggested: Mapped[dict[str, Any]] = mapped_column(JSONB)
    final: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
