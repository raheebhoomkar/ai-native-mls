"""AI runs on a listing's photos. Suggestions are stored on the run only. An editor reviews
each one; accepted or edited values become listing features. Listing columns are never written.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.ai.gemini import GeminiVisionProvider
from app.modules.ai.models import AgentRun
from app.modules.ai.providers import (
    DemoVisionProvider,
    MalformedOutput,
    Photo,
    ProviderError,
    VisionProvider,
)
from app.modules.ai.schemas import Extraction, Feature
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.media import service as media
from app.modules.organisations.deps import TenantContext
from app.modules.review import service as review
from app.modules.review.models import ReviewDecision

AGENT = "vision_extraction"
AGENT_VERSION = "1"
MAX_PHOTOS = 10
MAX_ATTEMPTS = 3
# Malformed output gets one more try, not the full set of attempts.
MALFORMED_MAX_ATTEMPTS = 2
REVIEW_SUBJECT = "agent_run"

Decision = Literal["accepted", "edited", "rejected"]


def get_provider() -> VisionProvider:
    """Gemini when a key is set; otherwise the demo adapter, whose output says it is demo."""
    settings = get_settings()
    if settings.gemini_api_key is None:
        return DemoVisionProvider()
    return GeminiVisionProvider(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.ai_timeout_seconds,
    )


def request_extraction(session: Session, ctx: TenantContext, listing_id: UUID) -> AgentRun:
    """Queue a vision extraction over the listing's newest ready photos. Editors only."""
    listing, assets = media.list_media(session, ctx, listing_id)  # 404 if not visible
    if not listings.can_edit(ctx, listing):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    ready = [asset for asset in assets if asset.status == "ready"][-MAX_PHOTOS:]
    if not ready:
        raise AppError(409, "no_photos", "Add a photo first. Photos still processing are skipped.")

    run = AgentRun(
        organisation_id=listing.organisation_id,
        listing_id=listing.id,
        requested_by_user_id=ctx.user.id,
        agent=AGENT,
        agent_version=AGENT_VERSION,
        inputs=[{"media_asset_id": str(asset.id), "sha256": asset.sha256} for asset in ready],
        status="queued",
    )
    session.add(run)
    session.flush()
    job = jobs.enqueue(
        session,
        "ai.extract",
        {"run_id": str(run.id)},
        organisation_id=listing.organisation_id,
        max_attempts=MAX_ATTEMPTS,
    )
    run.job_id = job.id
    session.flush()
    return run


def list_runs(session: Session, ctx: TenantContext, listing_id: UUID) -> Sequence[AgentRun]:
    """Newest first. Whoever may read the listing may read its runs."""
    listings.get_listing(session, ctx, listing_id)  # 404 if not visible
    return session.scalars(
        select(AgentRun)
        .where(AgentRun.listing_id == listing_id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    ).all()


# --- Background job ------------------------------------------------------------------------


def _fail_run(run: AgentRun, error: str) -> None:
    run.status = "failed"
    run.error = error
    run.finished_at = datetime.now(UTC)


def _extraction_failed(session: Session, job: Job) -> None:
    run = session.get(AgentRun, UUID(job.payload["run_id"]))
    if run is not None and run.status in ("queued", "running"):
        run.attempts = job.attempts
        _fail_run(run, job.last_error or "The extraction failed.")


@jobs.handler("ai.extract", on_failed=_extraction_failed)
def run_extraction(session: Session, job: Job) -> None:
    """Retryable provider errors re-raise, so the job backoff tries again (30 s, then 60 s).

    shortcut: the backoff ignores `RateLimited.retry_after`; use `jobs.enqueue(..., delay=...)`
    if 429s become common.
    """
    run = session.get(AgentRun, UUID(job.payload["run_id"]))
    if run is None or run.status in ("succeeded", "failed"):
        return
    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.attempts = job.attempts

    photos = []
    for item in run.inputs:
        try:
            asset, data = media.get_content(session, UUID(item["media_asset_id"]))
            # Originals keep camera metadata (GPS); the provider gets pixels only.
            clean = media.without_metadata(data)
        except AppError, OSError, ValueError:
            continue  # deleted since the request, or unreadable
        photos.append(Photo(media_asset_id=asset.id, content_type="image/jpeg", data=clean))
    if not photos:
        _fail_run(run, "The photos were removed before the extraction ran.")
        return

    try:
        result = get_provider().extract(photos)
    except ProviderError as error:
        last_malformed = (
            isinstance(error, MalformedOutput) and job.attempts >= MALFORMED_MAX_ATTEMPTS
        )
        if not error.retryable or last_malformed:
            _fail_run(run, f"{type(error).__name__}: {error}")
            return
        raise

    run.output = result.extraction.model_dump(mode="json")
    run.provider = result.provider
    run.model = result.model
    run.model_version = result.model_version
    run.status = "succeeded"
    run.error = None
    run.finished_at = datetime.now(UTC)
    if items(run):
        review.open_task(
            session,
            organisation_id=run.organisation_id,
            subject_type=REVIEW_SUBJECT,
            subject_id=str(run.id),
        )


# --- Review --------------------------------------------------------------------------------


def items(run: AgentRun) -> dict[str, Feature]:
    """Each suggestion of a run by its review key, `<media_asset_id>:<index>`."""
    if run.output is None:
        return {}
    extraction = Extraction.model_validate(run.output)
    return {
        f"{photo.media_asset_id}:{index}": feature
        for photo in extraction.photos
        for index, feature in enumerate(photo.features)
    }


def decide(
    session: Session,
    ctx: TenantContext,
    run_id: UUID,
    *,
    item_key: str,
    decision: Decision,
    value: str | None = None,
    note: str | None = None,
) -> ReviewDecision:
    """Record an editor's decision on one suggestion. Accepted or edited values are added to
    the listing's features; nothing else on the listing changes.
    """
    run = session.get(AgentRun, run_id)
    try:
        listing = listings.get_listing(session, ctx, run.listing_id) if run else None
    except AppError:
        listing = None  # same answer whether the run exists or not
    if run is None or listing is None:
        raise AppError(404, "not_found", "AI run not found.")
    if not listings.can_edit(ctx, listing):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    task = review.get_task_for(session, REVIEW_SUBJECT, str(run.id))
    feature = items(run).get(item_key)
    if task is None or feature is None:
        raise AppError(404, "not_found", "Suggestion not found.")

    final = feature.value if decision == "accepted" else (value or "").strip()
    if decision == "edited" and not 1 <= len(final) <= 120:
        raise AppError(422, "validation_error", "Enter a value of 1 to 120 characters.")
    row = review.decide(
        session,
        task,
        item_key=item_key,
        decision=decision,
        suggested=feature.model_dump(mode="json"),
        final=None if decision == "rejected" else {"attribute": feature.attribute, "value": final},
        note=(note or "").strip() or None,
        user_id=ctx.user.id,
    )
    if decision != "rejected":
        listings.add_feature(
            session,
            ctx,
            listing,
            attribute=feature.attribute,
            value=final,
            media_asset_id=UUID(item_key.split(":")[0]),
        )
    if len(review.decisions_for(session, [task.id])) == len(items(run)):
        review.close(task)
    return row
