from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.organisations.deps import TenantContext, require
from app.modules.workflow import service
from app.modules.workflow.models import WorkflowRun

listing_workflows_router = APIRouter(prefix="/listings/{listing_id}/workflows", tags=["workflow"])
workflows_router = APIRouter(prefix="/workflows", tags=["workflow"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]


class StepOut(BaseModel):
    name: str
    status: str
    attempts: int
    output: dict[str, Any]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowRunOut(BaseModel):
    id: UUID
    listing_id: UUID
    workflow: str
    workflow_version: str
    status: str
    trace_id: str | None
    passes: int
    max_passes: int
    deadline: datetime
    error: str | None
    requested_by_user_id: UUID
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[StepOut]


def run_out(session: Session, run: WorkflowRun) -> WorkflowRunOut:
    steps = [
        StepOut.model_validate(step, from_attributes=True)
        for step in service.steps_of(session, run)
    ]
    return WorkflowRunOut.model_validate(
        {
            **{k: getattr(run, k) for k in WorkflowRunOut.model_fields if k != "steps"},
            "steps": steps,
        }
    )


@listing_workflows_router.post("", status_code=202, responses=_ERRORS)
def start_workflow(
    listing_id: UUID, request: Request, session: SessionDep, ctx: CanRead
) -> WorkflowRunOut:
    """Run the listing workflow: locate, extract from photos, policy check, index, value.
    Editors of the owning organisation only; one run at a time per listing (409)."""
    run = service.start(session, ctx, listing_id)
    audit.record(
        session,
        "workflow.started",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="listing",
        target_id=str(listing_id),
        ip_address=client_ip(request),
        detail={"run_id": str(run.id), "workflow": run.workflow, "version": run.workflow_version},
    )
    return run_out(session, run)


@listing_workflows_router.get("", responses=_ERRORS)
def list_workflows(listing_id: UUID, session: SessionDep, ctx: CanRead) -> list[WorkflowRunOut]:
    """The 20 newest runs on a listing, newest first. Owning organisation only."""
    return [run_out(session, run) for run in service.list_runs(session, ctx, listing_id)]


@workflows_router.get("/{run_id}", responses=_ERRORS)
def get_workflow(run_id: UUID, session: SessionDep, ctx: CanRead) -> WorkflowRunOut:
    return run_out(session, service.get_run(session, ctx, run_id))
