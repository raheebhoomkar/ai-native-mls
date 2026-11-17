"""Operations: platform-wide health numbers with alerts in plain words, and the daily cleanup.

No tables of its own; it reads other modules through their services.
"""

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ai import service as ai
from app.modules.apikeys import service as apikeys
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.webhooks import service as webhooks

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)
CLEANUP_KIND = "ops.cleanup"
CLEANUP_EVERY = timedelta(hours=24)
KEEP_USAGE_FOR = timedelta(days=90)
KEEP_SUCCEEDED_JOBS_FOR = timedelta(days=30)
# How long one GET /ops/run-jobs call keeps taking jobs; below a serverless request timeout.
RUN_JOBS_SECONDS = 50.0
# Any fixed number; workers hold it while deciding whether to queue the cleanup.
_CLEANUP_LOCK = 2_100_000_021


def status(session: Session) -> dict[str, object]:
    since = datetime.now(UTC) - WINDOW
    job_counts = jobs.counts(session, since)
    unknown = jobs.unknown_kinds(session)
    delivery_counts = webhooks.counts(session, since)
    ai_failed, ai_last_error = ai.failures_since(session, since)

    alerts: list[str] = []
    if job_counts["overdue"]:
        alerts.append(
            f"Background jobs waiting over 5 minutes: {job_counts['overdue']}. "
            "Check that the worker is running."
        )
    if unknown:
        alerts.append(
            f"No handler runs these job kinds: {', '.join(unknown)}. "
            "A worker may be running older or newer code than the API."
        )
    if job_counts["failed_recently"]:
        alerts.append(
            f"Background jobs failed in the last 24 hours: {job_counts['failed_recently']}."
        )
    if job_counts["failed_platform"]:
        alerts.append(
            f"Failed platform jobs: {job_counts['failed_platform']}. "
            "No organisation's Monitor page shows them."
        )
    if delivery_counts["failed_recently"]:
        alerts.append(
            f"Webhook deliveries failed in the last 24 hours: {delivery_counts['failed_recently']}."
        )
    if ai_failed:
        alerts.append(f"AI extraction runs failed in the last 24 hours: {ai_failed}.")

    return {
        "checked_at": datetime.now(UTC),
        "jobs": {**job_counts, "unknown_kinds": unknown},
        "webhook_deliveries": delivery_counts,
        "ai": {"failed_recently": ai_failed, "last_error": ai_last_error},
        "alerts": alerts,
    }


@jobs.handler(CLEANUP_KIND)
def cleanup(session: Session, job: Job) -> None:
    """Delete rows past their retention period. Safe to run more than once."""
    now = datetime.now(UTC)
    deleted = apikeys.delete_expired(session, usage_before=now - KEEP_USAGE_FOR)
    deleted["succeeded_jobs"] = jobs.delete_succeeded_before(session, now - KEEP_SUCCEEDED_JOBS_FOR)
    logger.info("Cleanup finished", extra={"deleted": deleted})


def ensure_cleanup_scheduled(session: Session) -> Job | None:
    """Queue the cleanup unless one is waiting or ran in the last day. Commits."""
    session.execute(select(func.pg_advisory_xact_lock(_CLEANUP_LOCK)))
    job = None
    if not jobs.exists_since(session, CLEANUP_KIND, datetime.now(UTC) - CLEANUP_EVERY):
        job = jobs.enqueue(session, CLEANUP_KIND)
    session.commit()
    return job


def run_jobs(session: Session, seconds: float = RUN_JOBS_SECONDS) -> int:
    """Queue the cleanup if due, then run due jobs until none is left or `seconds` pass.

    For hosts without an always-on worker: a scheduler calls this over HTTP. A job still
    running at the deadline finishes first. Returns how many jobs ran, whatever their outcome.
    """
    ensure_cleanup_scheduled(session)
    deadline = time.monotonic() + seconds
    ran = 0
    while time.monotonic() < deadline and jobs.run_one(session):
        ran += 1
    return ran
