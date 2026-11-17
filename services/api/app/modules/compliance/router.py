from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.ai.models import AgentRun
from app.modules.auth.deps import client_ip
from app.modules.compliance import service
from app.modules.compliance.schemas import ComplianceScan, ScanOut
from app.modules.organisations.deps import TenantContext, require

listing_scans_router = APIRouter(
    prefix="/listings/{listing_id}/compliance/scans", tags=["compliance"]
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]


def scan_out(run: AgentRun) -> ScanOut:
    return ScanOut(
        id=run.id,
        listing_id=run.listing_id,
        status=run.status,
        listing_version=run.inputs[0]["listing_version"],
        provider=run.provider,
        model=run.model,
        model_version=run.model_version,
        output=ComplianceScan.model_validate(run.output) if run.output is not None else None,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        is_demo=run.provider == "demo",
    )


@listing_scans_router.post("", status_code=202, responses=_ERRORS)
def request_scan(listing_id: UUID, request: Request, ctx: CanWrite, session: SessionDep) -> ScanOut:
    """Check the listing's title and remarks against the listing policy. Poll the list until
    the scan finishes. Findings are for a person to review; the listing is never changed.
    """
    run = service.request_scan(session, ctx, listing_id)
    service.record_requested(session, ctx, run, client_ip(request))
    session.refresh(run)  # server-set created_at
    return scan_out(run)


@listing_scans_router.get("", responses=_ERRORS)
def list_scans(listing_id: UUID, ctx: CanRead, session: SessionDep) -> list[ScanOut]:
    """Newest first. Only the organisation that owns the listing sees them."""
    return [scan_out(run) for run in service.list_scans(session, ctx, listing_id)]
