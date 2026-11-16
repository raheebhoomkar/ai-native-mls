from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job

calls: list[str] = []


@jobs.handler("test.ok")
def _ok(session: Session, job: Job) -> None:
    calls.append(job.payload["name"])


@jobs.handler("test.boom")
def _boom(session: Session, job: Job) -> None:
    audit.record(session, "test.partial_work")  # must be rolled back with the failure
    raise RuntimeError("disk full")


@pytest.fixture(autouse=True)
def _reset_calls() -> None:
    calls.clear()


def _past() -> datetime:
    return datetime.now(UTC) - timedelta(hours=1)


def test_job_runs_once_and_succeeds(db: Session) -> None:
    job = jobs.enqueue(db, "test.ok", {"name": "first"})
    db.commit()

    assert jobs.run_one(db) is True
    assert jobs.run_one(db) is False

    db.refresh(job)
    assert calls == ["first"]
    assert (job.status, job.attempts, job.last_error) == ("succeeded", 1, None)
    assert job.finished_at is not None


def test_failed_job_is_retried_with_backoff_then_marked_failed(db: Session) -> None:
    job = jobs.enqueue(db, "test.boom", max_attempts=2)
    db.commit()

    assert jobs.run_one(db) is True
    db.refresh(job)
    assert (job.status, job.attempts) == ("queued", 1)
    assert job.last_error == "RuntimeError: disk full"
    assert job.run_after > db.scalars(select(func.now())).one()
    assert jobs.run_one(db) is False  # not due until the backoff passes

    job.run_after = _past()
    db.commit()
    assert jobs.run_one(db) is True
    db.refresh(job)
    assert (job.status, job.attempts) == ("failed", 2)
    assert job.finished_at is not None
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "test.partial_work")) is None


def test_unknown_kind_fails_without_retrying(db: Session) -> None:
    job = jobs.enqueue(db, "test.nobody_handles_this")
    db.commit()

    assert jobs.run_one(db) is True
    db.refresh(job)
    assert (job.status, job.attempts) == ("failed", 1)
    assert "No handler registered" in (job.last_error or "")


def test_job_due_later_is_not_claimed(db: Session) -> None:
    job = jobs.enqueue(db, "test.ok", {"name": "later"})
    job.run_after = datetime.now(UTC) + timedelta(hours=1)
    db.commit()

    assert jobs.run_one(db) is False
    assert calls == []


def test_job_of_a_dead_worker_is_reclaimed(db: Session) -> None:
    job = jobs.enqueue(db, "test.ok", {"name": "reclaimed"})
    job.status, job.attempts, job.locked_at = "running", 1, _past()
    db.commit()

    assert jobs.run_one(db) is True
    db.refresh(job)
    assert calls == ["reclaimed"]
    assert (job.status, job.attempts) == ("succeeded", 2)


def test_running_job_within_its_lease_is_left_alone(db: Session) -> None:
    job = jobs.enqueue(db, "test.ok", {"name": "busy"})
    job.status, job.attempts, job.locked_at = "running", 1, datetime.now(UTC)
    db.commit()

    assert jobs.run_one(db) is False


def test_dead_worker_on_last_attempt_fails_the_job(db: Session) -> None:
    job = jobs.enqueue(db, "test.ok", {"name": "never"}, max_attempts=1)
    job.status, job.attempts, job.locked_at = "running", 1, _past()
    db.commit()

    assert jobs.run_one(db) is True
    db.refresh(job)
    assert calls == []
    assert job.status == "failed"
    assert job.last_error == "The worker stopped during the last attempt."


def test_retry_queues_a_failed_job_again(db: Session) -> None:
    job = jobs.enqueue(db, "test.boom", max_attempts=1)
    db.commit()
    jobs.run_one(db)
    db.refresh(job)
    assert job.status == "failed"

    jobs.retry(db, job)
    db.commit()
    db.refresh(job)
    assert (job.status, job.attempts, job.finished_at) == ("queued", 0, None)
    assert job.last_error == "RuntimeError: disk full"  # kept until the next attempt

    with pytest.raises(ValueError, match="Only a failed job"):
        jobs.retry(db, job)


def test_a_kind_cannot_have_two_handlers() -> None:
    with pytest.raises(ValueError, match="already registered"):
        jobs.handler("test.ok")(_boom)


failed_hook_calls: list[str] = []


def _record_failure(session: Session, job: Job) -> None:
    failed_hook_calls.append(job.kind)


@jobs.handler("test.boom_with_hook", on_failed=_record_failure)
def _boom_with_hook(session: Session, job: Job) -> None:
    raise RuntimeError("still broken")


def test_failure_hook_runs_once_when_the_job_fails_for_good(db: Session) -> None:
    failed_hook_calls.clear()
    job = jobs.enqueue(db, "test.boom_with_hook", max_attempts=2)
    db.commit()

    jobs.run_one(db)
    assert failed_hook_calls == []  # will be retried
    job.run_after = _past()
    db.commit()
    jobs.run_one(db)
    assert failed_hook_calls == ["test.boom_with_hook"]


def test_delayed_job_waits(db: Session) -> None:
    job = jobs.enqueue(db, "test.ok", {"name": "delayed"}, delay=timedelta(minutes=5))
    db.commit()

    assert jobs.run_one(db) is False
    job.run_after = _past()
    db.commit()
    assert jobs.run_one(db) is True
    assert calls == ["delayed"]
