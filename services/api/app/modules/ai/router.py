from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.ai import service
from app.modules.ai.models import AgentRun
from app.modules.ai.schemas import AgentRunOut, DecisionIn, DecisionOut, Extraction
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.listings import service as listings
from app.modules.organisations.deps import TenantContext, require
from app.modules.review.models import ReviewDecision
from app.modules.workflow import service as workflow

router = APIRouter(prefix="/listings/{listing_id}/ai/extractions", tags=["ai"])
runs_router = APIRouter(prefix="/ai/runs", tags=["ai"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]


def _decision_out(row: ReviewDecision) -> DecisionOut:
    return DecisionOut(
        item_key=row.item_key or "",
        decision=row.decision,
        final_value=row.final["value"] if row.final else None,
        note=row.note,
        decided_by_user_id=row.decided_by_user_id,
        decided_at=row.decided_at,
    )


def _out(run: AgentRun, decisions: dict[str, ReviewDecision], *, can_review: bool) -> AgentRunOut:
    return AgentRunOut(
        id=run.id,
        listing_id=run.listing_id,
        status=run.status,
        agent=run.agent,
        agent_version=run.agent_version,
        provider=run.provider,
        model=run.model,
        model_version=run.model_version,
        inputs=run.inputs,
        output=Extraction.model_validate(run.output) if run.output is not None else None,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        is_demo=run.provider == "demo",
        decisions={key: _decision_out(row) for key, row in decisions.items()},
        can_review=can_review,
    )


@router.post("", status_code=202, responses=_ERRORS)
def request_extraction(
    listing_id: UUID, request: Request, ctx: CanWrite, session: SessionDep
) -> AgentRunOut:
    """Queue photo extraction. Poll the list until the run succeeds or fails."""
    run = service.request_extraction(session, ctx, listing_id)
    audit.record(
        session,
        "ai.extraction_requested",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="agent_run",
        target_id=str(run.id),
        ip_address=client_ip(request),
        detail={"listing_id": str(listing_id), "photos": len(run.inputs)},
    )
    session.refresh(run)  # server-set created_at
    return _out(run, {}, can_review=True)


@router.get("", responses=_ERRORS)
def list_extractions(listing_id: UUID, ctx: CanRead, session: SessionDep) -> list[AgentRunOut]:
    runs = service.list_runs(session, ctx, listing_id)  # 404 if the listing is not visible
    can_review = listings.can_edit(ctx, listings.get_listing(session, ctx, listing_id))
    return [_out(run, service.decisions(session, run), can_review=can_review) for run in runs]


@runs_router.post("/{run_id}/decisions", status_code=201, responses=_ERRORS)
def decide(
    run_id: UUID, body: DecisionIn, request: Request, ctx: CanWrite, session: SessionDep
) -> DecisionOut:
    """Accept, edit or reject one suggestion. Accepted or edited values become listing
    features; listing fields are never changed. One decision per suggestion.
    """
    row = service.decide(
        session,
        ctx,
        run_id,
        item_key=body.item_key,
        decision=body.decision,
        value=body.value,
        note=body.note,
    )
    workflow.wake(session, session.get_one(AgentRun, run_id).listing_id)
    audit.record(
        session,
        "ai.suggestion_decided",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="agent_run",
        target_id=str(run_id),
        ip_address=client_ip(request),
        detail={"item_key": body.item_key, "decision": body.decision},
    )
    session.refresh(row)  # server-set decided_at
    return _decision_out(row)
