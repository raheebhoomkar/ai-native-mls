"""Photo redaction (Module 5): find faces, licence plates, phone numbers, watermarks and signs,
and make a blurred copy that a person approves or rejects. The original is never changed.

Detection is not perfect. Every finished check goes to review, including one that found
nothing, and the run records what was not checked.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Literal
from uuid import UUID

from PIL import Image, ImageFilter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.ai.detectors import FaceDetector, OpenCvFaceDetector
from app.modules.ai.gemini import GeminiRegionLocator
from app.modules.ai.models import AgentRun
from app.modules.ai.providers import DemoRegionLocator, Photo, ProviderError, RegionLocator
from app.modules.ai.schemas import (
    LOCATED_CATEGORIES,
    DetectorUsed,
    Redaction,
    Region,
    Unchecked,
)
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.listings.models import Listing
from app.modules.media import service as media
from app.modules.organisations.deps import TenantContext
from app.modules.review import service as review
from app.modules.review.models import ReviewDecision

AGENT = "redaction"
AGENT_VERSION = "1"
# What is blurred. Change the version whenever the categories or the method change.
POLICY_VERSION = "1"
CATEGORIES: tuple[str, ...] = ("face", *LOCATED_CATEGORIES)
MAX_SIDE = 2048
MAX_ATTEMPTS = 3
# Each box grows by this share of its size on every side, so edges are covered too.
MARGIN = 0.15
REVIEW_SUBJECT = "redaction"

Decision = Literal["accepted", "rejected"]


def get_locator() -> RegionLocator:
    """Gemini when a key is set; otherwise the demo locator, which checks nothing."""
    settings = get_settings()
    if settings.gemini_api_key is None:
        return DemoRegionLocator()
    return GeminiRegionLocator(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.ai_timeout_seconds,
    )


def get_face_detector() -> FaceDetector:
    return OpenCvFaceDetector()


def _photo_id(run: AgentRun) -> UUID:
    return UUID(run.inputs[0]["media_asset_id"])


def request_redaction(session: Session, ctx: TenantContext, asset_id: UUID) -> AgentRun:
    """Queue a check of one photo. Editors of an unarchived listing only."""
    original = media.get_manageable(session, ctx, asset_id)  # 404, 403 or 409 archived
    if original.status != "ready":
        raise AppError(409, "not_ready", "Wait until the photo has finished processing.")
    pending = session.scalars(
        select(AgentRun).where(
            AgentRun.listing_id == original.listing_id,
            AgentRun.agent == AGENT,
            AgentRun.status.in_(("queued", "running")),
        )
    ).all()
    if any(_photo_id(run) == original.id for run in pending):
        raise AppError(409, "redaction_in_progress", "This photo is already being checked.")

    run = AgentRun(
        organisation_id=original.organisation_id,
        listing_id=original.listing_id,
        requested_by_user_id=ctx.user.id,
        agent=AGENT,
        agent_version=AGENT_VERSION,
        inputs=[{"media_asset_id": str(original.id), "sha256": original.sha256}],
        status="queued",
    )
    session.add(run)
    session.flush()
    job = jobs.enqueue(
        session,
        "ai.redact",
        {"run_id": str(run.id)},
        organisation_id=original.organisation_id,
        max_attempts=MAX_ATTEMPTS,
    )
    run.job_id = job.id
    session.flush()
    return run


def list_redactions(
    session: Session, ctx: TenantContext, listing_id: UUID
) -> tuple[Listing, Sequence[AgentRun]]:
    """Newest first, for the listing's current photos. Whoever may read the listing may read."""
    listing, originals = media.list_media(session, ctx, listing_id)  # 404 if not visible
    current = {asset.id for asset in originals}
    runs = session.scalars(
        select(AgentRun)
        .where(AgentRun.listing_id == listing_id, AgentRun.agent == AGENT)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    ).all()
    return listing, [run for run in runs if _photo_id(run) in current]


def decision_for(session: Session, run: AgentRun) -> ReviewDecision | None:
    task = review.get_task_for(session, REVIEW_SUBJECT, str(run.id))
    rows = review.decisions_for(session, [task.id]) if task else []
    return rows[0] if rows else None


def decide(
    session: Session,
    ctx: TenantContext,
    run_id: UUID,
    *,
    decision: Decision,
    note: str | None = None,
) -> ReviewDecision:
    """Approve (`accepted`) or reject a redacted copy. One decision per run, never replaced."""
    run = session.get(AgentRun, run_id)
    listing = None
    if run is not None and run.agent == AGENT:
        try:
            listing, originals = media.list_media(session, ctx, run.listing_id)
        except AppError:
            pass  # same answer whether the run exists or not
        else:
            if _photo_id(run) not in {asset.id for asset in originals}:
                listing = None  # the photo was removed
    if run is None or listing is None:
        raise AppError(404, "not_found", "Redaction not found.")
    if not listings.can_edit(ctx, listing):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    task = review.get_task_for(session, REVIEW_SUBJECT, str(run.id))
    if task is None or run.output is None:
        raise AppError(409, "not_finished", "This check has not finished.")

    derivative = {"derivative_id": run.output["derivative_id"]}
    row = review.decide(
        session,
        task,
        item_key=None,
        decision=decision,
        suggested={**derivative, "regions": len(run.output["regions"])},
        final=derivative if decision == "accepted" else None,
        note=(note or "").strip() or None,
        user_id=ctx.user.id,
    )
    review.close(task)
    return row


# --- Background job ------------------------------------------------------------------------


def blur(image: Image.Image, regions: Sequence[Region]) -> Image.Image:
    """A copy with each region (plus a margin) pixelated, then blurred. Not reversible."""
    out = image.copy()
    width, height = out.size
    for region in regions:
        left, top, w, h = region.box
        x0 = max(0, int((left - w * MARGIN) * width))
        y0 = max(0, int((top - h * MARGIN) * height))
        x1 = min(width, round((left + w * (1 + MARGIN)) * width))
        y1 = min(height, round((top + h * (1 + MARGIN)) * height))
        if x1 <= x0 or y1 <= y0:
            continue
        patch = out.crop((x0, y0, x1, y1))
        # About six blocks across the short side; tested so the face detector no longer fires.
        block = max(4, min(x1 - x0, y1 - y0) // 6)
        small = patch.resize(
            (max(1, (x1 - x0) // block), max(1, (y1 - y0) // block)), Image.Resampling.BOX
        )
        pixelated = small.resize(patch.size, Image.Resampling.NEAREST)
        out.paste(pixelated.filter(ImageFilter.GaussianBlur(block)), (x0, y0))
    return out


def _fail_run(run: AgentRun, error: str) -> None:
    run.status = "failed"
    run.error = error
    run.finished_at = datetime.now(UTC)


def _redaction_failed(session: Session, job: Job) -> None:
    run = session.get(AgentRun, UUID(job.payload["run_id"]))
    if run is not None and run.status in ("queued", "running"):
        run.attempts = job.attempts
        _fail_run(run, job.last_error or "The check failed.")


@jobs.handler("ai.redact", on_failed=_redaction_failed)
def run_redaction(session: Session, job: Job) -> None:
    """A retryable locator error re-raises until the last attempt; then the run finishes
    without those categories and says so, so faces are still blurred.
    """
    run = session.get(AgentRun, UUID(job.payload["run_id"]))
    if run is None or run.status in ("succeeded", "failed"):
        return
    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.attempts = job.attempts

    try:
        original, data = media.get_content(session, _photo_id(run))
        # Upright, metadata-free pixels: what is checked, blurred and sent to the locator.
        clean = media.without_metadata(data, MAX_SIDE)
        with Image.open(BytesIO(clean)) as opened:
            image = opened.convert("RGB")
    except AppError:
        _fail_run(run, "The photo was removed before the check ran.")
        return
    except OSError, ValueError:
        _fail_run(run, "The photo could not be read.")
        return

    regions: list[Region] = []
    checked: list[DetectorUsed] = []
    unchecked: list[Unchecked] = []

    detector = get_face_detector()
    regions += detector.detect(image)
    checked.append(
        DetectorUsed(detector=detector.name, version=detector.version, categories=["face"])
    )
    run.provider, run.model = "opencv", detector.version

    located = list(LOCATED_CATEGORIES)
    try:
        result = get_locator().locate(
            Photo(media_asset_id=original.id, content_type="image/jpeg", data=clean)
        )
    except ProviderError as error:
        if error.retryable and job.attempts < job.max_attempts:
            raise
        unchecked.append(Unchecked(categories=located, reason=f"The text check failed: {error}"))
    else:
        run.provider, run.model, run.model_version = (
            result.provider,
            result.model,
            result.model_version,
        )
        if result.provider == "demo":
            reason = "No vision model is configured (demo mode), so these were not looked for."
            unchecked.append(Unchecked(categories=located, reason=reason))
        else:
            regions += result.regions
            version = result.model_version or result.model
            checked.append(
                DetectorUsed(detector=result.provider, version=version, categories=located)
            )

    out = BytesIO()
    blur(image, regions).save(out, "JPEG", quality=85, optimize=True)
    derivative = media.add_derivative(session, original, out.getvalue(), kind="redacted")

    run.output = Redaction(
        policy_version=POLICY_VERSION,
        width=image.width,
        height=image.height,
        regions=regions,
        checked=checked,
        unchecked=unchecked,
        derivative_id=derivative.id,
    ).model_dump(mode="json")
    run.status = "succeeded"
    run.error = None
    run.finished_at = datetime.now(UTC)
    review.open_task(
        session,
        organisation_id=run.organisation_id,
        subject_type=REVIEW_SUBJECT,
        subject_id=str(run.id),
    )
