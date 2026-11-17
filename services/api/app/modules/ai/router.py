from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.ai import service
from app.modules.ai.models import AgentRun
from app.modules.ai.schemas import AgentRunOut, Extraction
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.organisations.deps import TenantContext, require

router = APIRouter(prefix="/listings/{listing_id}/ai/extractions", tags=["ai"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]


def _out(run: AgentRun) -> AgentRunOut:
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
    return _out(run)


@router.get("", responses=_ERRORS)
def list_extractions(listing_id: UUID, ctx: CanRead, session: SessionDep) -> list[AgentRunOut]:
    return [_out(run) for run in service.list_runs(session, ctx, listing_id)]
