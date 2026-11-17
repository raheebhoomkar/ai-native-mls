from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

RUN_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "waiting",  # a step is waiting for background work; the run resumes on its own
    "awaiting_review",  # a person must decide before the run can go on (Sprint 16)
    "succeeded",
    "failed",
    "cancelled",
)
STEP_STATUSES: tuple[str, ...] = ("pending", "waiting", "succeeded", "failed", "skipped")


class WorkflowRun(Base):
    """One pass of the listing workflow (the LangGraph graph in workflow/graph.py).

    The graph's state is rebuilt from this row and its steps on every pass, so a pass that
    dies half way is simply run again: finished steps are not repeated.
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(one_of("status", RUN_STATUSES), name="ck_workflow_runs_status"),
        CheckConstraint("passes >= 0 AND max_passes >= 1", name="ck_workflow_runs_passes"),
        Index("ix_workflow_runs_listing_created", "listing_id", "created_at"),
        Index("ix_workflow_runs_organisation_created", "organisation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"))
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    workflow: Mapped[str] = mapped_column(String(50))
    workflow_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # The request ID that started the run; every job and log line of the run carries it.
    trace_id: Mapped[str | None] = mapped_column(String(100))
    # Budget: each pass is one worker job; a run that needs more passes, or outlives its
    # deadline, fails instead of polling for ever.
    passes: Mapped[int] = mapped_column(Integer, default=0)
    max_passes: Mapped[int] = mapped_column(Integer, default=180)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowStep(Base):
    """One node of a run. Unique per run and name, so a step can never run twice in parallel."""

    __tablename__ = "workflow_steps"
    __table_args__ = (
        CheckConstraint(one_of("status", STEP_STATUSES), name="ck_workflow_steps_status"),
        CheckConstraint("attempts >= 0", name="ck_workflow_steps_attempts"),
        UniqueConstraint("run_id", "name", name="uq_workflow_steps_run_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # What the step made: IDs of the agent run, valuation and so on, plus a short summary.
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
