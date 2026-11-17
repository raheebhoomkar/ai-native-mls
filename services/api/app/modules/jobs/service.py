"""Postgres-backed job queue. No Redis: the job row is written in the same transaction
as the change that needs it, so a job exists if and only if that change committed.

Usage:

    @jobs.handler("media.thumbnail")
    def make_thumbnail(session: Session, job: Job) -> None: ...

    jobs.enqueue(session, "media.thumbnail", {"asset_id": str(asset.id)}, organisation_id=...)

A worker (`python -m app.worker`) calls `run_one` in a loop. Handlers must be safe to run
more than once for the same job: a job is retried after an error, and reclaimed if its
worker dies mid-run.
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.modules.jobs.models import Job

logger = logging.getLogger(__name__)

Handler = Callable[[Session, Job], None]

# A running job whose worker has not finished it within this time is taken over.
LEASE = timedelta(minutes=15)
# Wait before retry n is BACKOFF * 2**(n-1): 30 s, 60 s, 120 s, ...
BACKOFF = timedelta(seconds=30)
_MAX_ERROR_LENGTH = 2000

_handlers: dict[str, Handler] = {}
_failure_handlers: dict[str, Handler] = {}


def handler(kind: str, *, on_failed: Handler | None = None) -> Callable[[Handler], Handler]:
    """Register the function that runs jobs of `kind`. One handler per kind.

    `on_failed` runs once, in the transaction that marks the job failed for good, so the
    caller can record the failure on its own records (for example, show it to a user).
    """

    def _register(function: Handler) -> Handler:
        if kind in _handlers and _handlers[kind] is not function:
            raise ValueError(f"A handler for job kind {kind!r} is already registered.")
        _handlers[kind] = function
        if on_failed is not None:
            _failure_handlers[kind] = on_failed
        return function

    return _register


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    organisation_id: UUID | None = None,
    max_attempts: int = 3,
    delay: timedelta | None = None,
) -> Job:
    """Add a job to the caller's transaction. It becomes visible to workers on commit."""
    payload = dict(payload or {})
    # Carry the request's ID into the job, so a trace runs from the request to the agent call.
    trace_id = request_id_var.get()
    if trace_id is not None:
        payload.setdefault("trace_id", trace_id)
    job = Job(
        kind=kind,
        payload=payload,
        organisation_id=organisation_id,
        max_attempts=max_attempts,
    )
    if delay is not None:
        job.run_after = func.now() + delay
    session.add(job)
    session.flush()
    return job


def _claim(session: Session) -> Job | None:
    """Lock the next due job, or a running one whose lease ran out, and mark it running."""
    now = func.now()
    job = session.scalars(
        select(Job)
        .where(
            or_(
                and_(Job.status == "queued", Job.run_after <= now),
                and_(Job.status == "running", Job.locked_at < now - LEASE),
            )
        )
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    if job.status == "running" and job.attempts >= job.max_attempts:
        _fail(session, job, "The worker stopped during the last attempt.")
        return job
    job.status = "running"
    job.attempts += 1
    job.locked_at = now
    return job


def _finish(job: Job, status: str, error: str | None = None) -> None:
    job.status = status
    job.last_error = error
    job.locked_at = None
    job.finished_at = func.now()


def _fail(session: Session, job: Job, error: str) -> None:
    _finish(job, "failed", error)
    hook = _failure_handlers.get(job.kind)
    if hook is None:
        return
    try:
        with session.begin_nested():
            hook(session, job)
    except Exception:
        # The job stays failed either way; a broken hook must not stop the worker.
        logger.exception("Job failure hook failed", extra={"job_id": str(job.id)})


def run_one(session: Session) -> bool:
    """Run at most one job. Returns False when no job was due.

    Commits the session: once after claiming (so other workers skip the job and the lock
    is released while the handler runs), and once with the outcome.
    """
    job = _claim(session)
    session.commit()
    if job is None:
        return False
    if job.status != "running":
        return True  # failed during claim

    job_id = job.id
    function = _handlers.get(job.kind)
    token = request_id_var.set(job.payload.get("trace_id"))
    try:
        if function is None:
            raise LookupError(f"No handler registered for job kind {job.kind!r}.")
        function(session, job)
    except Exception as error:
        session.rollback()  # discard the handler's partial work, keep the job row
        logger.exception("Job failed", extra={"job_id": str(job_id)})
        failed = session.get_one(Job, job_id)
        message = f"{type(error).__name__}: {error}"[:_MAX_ERROR_LENGTH]
        if function is not None and failed.attempts < failed.max_attempts:
            failed.status = "queued"
            failed.last_error = message
            failed.locked_at = None
            failed.run_after = func.now() + BACKOFF * 2 ** (failed.attempts - 1)
        else:
            _fail(session, failed, message)
    else:
        _finish(job, "succeeded")
    finally:
        request_id_var.reset(token)
    session.commit()
    return True


def get_job(session: Session, job_id: UUID) -> Job | None:
    return session.get(Job, job_id)


def count_failed(session: Session, organisation_id: UUID) -> int:
    query = select(func.count()).where(
        Job.organisation_id == organisation_id, Job.status == "failed"
    )
    return session.scalar(query) or 0


def retry(session: Session, job: Job) -> Job:
    """Queue a failed job again with a fresh set of attempts. Callers check permissions."""
    if job.status != "failed":
        raise ValueError("Only a failed job can be retried.")
    job.status = "queued"
    job.attempts = 0
    job.run_after = func.now()
    job.finished_at = None
    session.flush()
    return job
