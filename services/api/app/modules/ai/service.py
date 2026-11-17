"""AI runs on a listing's photos. Suggestions are stored on the run only; nothing here writes
to listing fields (an editor accepts suggestions in Sprint 8).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
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
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.media import service as media
from app.modules.organisations.deps import TenantContext

AGENT = "vision_extraction"
AGENT_VERSION = "1"
MAX_PHOTOS = 10
MAX_ATTEMPTS = 3
# Malformed output gets one more try, not the full set of attempts.
MALFORMED_MAX_ATTEMPTS = 2


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
