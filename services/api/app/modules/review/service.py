"""Generic review records. Callers check permissions and decide what a decision changes."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.review.models import ReviewDecision, ReviewTask


def open_task(
    session: Session, *, organisation_id: UUID, subject_type: str, subject_id: str
) -> ReviewTask:
    """Idempotent: a second call for the same subject returns the existing task."""
    task = get_task_for(session, subject_type, subject_id)
    if task is None:
        task = ReviewTask(
            organisation_id=organisation_id, subject_type=subject_type, subject_id=subject_id
        )
        session.add(task)
        session.flush()
    return task


def get_task_for(session: Session, subject_type: str, subject_id: str) -> ReviewTask | None:
    return session.scalar(
        select(ReviewTask).where(
            ReviewTask.subject_type == subject_type, ReviewTask.subject_id == subject_id
        )
    )


def decisions_for(session: Session, task_ids: Sequence[UUID]) -> Sequence[ReviewDecision]:
    if not task_ids:
        return []
    return session.scalars(
        select(ReviewDecision)
        .where(ReviewDecision.task_id.in_(task_ids))
        .order_by(ReviewDecision.decided_at, ReviewDecision.id)
    ).all()


def decide(
    session: Session,
    task: ReviewTask,
    *,
    item_key: str | None,
    decision: str,
    suggested: dict[str, Any],
    final: dict[str, Any] | None,
    note: str | None,
    user_id: UUID,
) -> ReviewDecision:
    """Record a decision. A second decision on the same item is refused, never replaced."""
    if task.status != "open":
        raise AppError(409, "review_closed", "This review is already finished.")
    row = ReviewDecision(
        task_id=task.id,
        item_key=item_key,
        decision=decision,
        suggested=suggested,
        final=final,
        note=note,
        decided_by_user_id=user_id,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        raise AppError(409, "already_decided", "This suggestion already has a decision.") from None
    return row


def close(task: ReviewTask) -> None:
    task.status = "closed"
    task.closed_at = datetime.now(UTC)
