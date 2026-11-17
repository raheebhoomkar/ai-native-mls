from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.ai import redaction as service
from app.modules.ai.models import AgentRun
from app.modules.ai.schemas import (
    Redaction,
    RedactionDecisionIn,
    RedactionDecisionOut,
    RedactionRunOut,
)
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.listings import service as listings
from app.modules.media import service as media
from app.modules.organisations.deps import TenantContext, require
from app.modules.review.models import ReviewDecision

media_redactions_router = APIRouter(prefix="/media/{asset_id}/redactions", tags=["ai"])
listing_redactions_router = APIRouter(prefix="/listings/{listing_id}/redactions", tags=["ai"])
redactions_router = APIRouter(prefix="/ai/redactions", tags=["ai"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]

_REVIEW_STATUS = {"accepted": "approved", "rejected": "rejected"}


def _decision_out(row: ReviewDecision) -> RedactionDecisionOut:
    return RedactionDecisionOut(
        decision=row.decision,
        note=row.note,
        decided_by_user_id=row.decided_by_user_id,
        decided_at=row.decided_at,
    )


def _out(run: AgentRun, decision: ReviewDecision | None, *, can_review: bool) -> RedactionRunOut:
    output = Redaction.model_validate(run.output) if run.output is not None else None
    status = None
    if output is not None:
        status = _REVIEW_STATUS[decision.decision] if decision else "pending"
    return RedactionRunOut(
        id=run.id,
        listing_id=run.listing_id,
        media_asset_id=UUID(run.inputs[0]["media_asset_id"]),
        status=run.status,
        agent_version=run.agent_version,
        provider=run.provider,
        model=run.model,
        model_version=run.model_version,
        output=output,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        is_demo=run.provider == "demo",
        redacted_url=media.signed_url(output.derivative_id) if output else None,
        review_status=status,
        decision=_decision_out(decision) if decision else None,
        can_review=can_review,
    )


@media_redactions_router.post("", status_code=202, responses=_ERRORS)
def request_redaction(
    asset_id: UUID, request: Request, ctx: CanWrite, session: SessionDep
) -> RedactionRunOut:
    """Check one photo for faces, plates, phone numbers, watermarks and signs, and make a
    blurred copy for review. Poll the listing's redactions until the run finishes.
    """
    run = service.request_redaction(session, ctx, asset_id)
    audit.record(
        session,
        "ai.redaction_requested",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="agent_run",
        target_id=str(run.id),
        ip_address=client_ip(request),
        detail={"listing_id": str(run.listing_id), "media_asset_id": str(asset_id)},
    )
    session.refresh(run)  # server-set created_at
    return _out(run, None, can_review=True)


@listing_redactions_router.get("", responses=_ERRORS)
def list_redactions(listing_id: UUID, ctx: CanRead, session: SessionDep) -> list[RedactionRunOut]:
    """Newest first, for the listing's current photos."""
    listing, runs = service.list_redactions(session, ctx, listing_id)
    can_review = listings.can_edit(ctx, listing)
    return [_out(run, service.decision_for(session, run), can_review=can_review) for run in runs]


@redactions_router.post("/{run_id}/decision", status_code=201, responses=_ERRORS)
def decide(
    run_id: UUID, body: RedactionDecisionIn, request: Request, ctx: CanWrite, session: SessionDep
) -> RedactionDecisionOut:
    """Approve or reject a redacted copy. One decision per check; the original never changes."""
    row = service.decide(session, ctx, run_id, decision=body.decision, note=body.note)
    audit.record(
        session,
        "ai.redaction_decided",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="agent_run",
        target_id=str(run_id),
        ip_address=client_ip(request),
        detail={"decision": body.decision},
    )
    session.refresh(row)  # server-set decided_at
    return _decision_out(row)
