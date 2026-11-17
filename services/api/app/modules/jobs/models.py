from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

JOB_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed")


class Job(Base):
    """Background work, queued in the same transaction as the change that needs it.

    Workers claim rows with `FOR UPDATE SKIP LOCKED`, so several can run at once
    without taking the same job. See app/modules/jobs/service.py.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(one_of("status", JOB_STATUSES), name="ck_jobs_status"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_jobs_attempts"),
        # Only unfinished jobs are ever polled, so keep the index small.
        Index(
            "ix_jobs_due",
            "run_after",
            postgresql_where="status IN ('queued', 'running')",
        ),
        Index("ix_jobs_organisation_created", "organisation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Set when the job works on one organisation's data; None for platform jobs.
    organisation_id: Mapped[UUID | None] = mapped_column(ForeignKey("organisations.id"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When the current attempt started; a running job older than the lease is reclaimed.
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
