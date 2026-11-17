from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.jobs import service
from app.modules.jobs.models import Job
from app.modules.organisations.deps import TenantContext, require

router = APIRouter(prefix="/jobs", tags=["jobs"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}

# Job errors can name internal details; only administrators see them.
CanMonitor = Annotated[TenantContext, Depends(require("audit:read"))]


class JobOut(BaseModel):
    id: UUID
    kind: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    trace_id: str | None
    created_at: datetime
    run_after: datetime
    finished_at: datetime | None


def job_out(job: Job) -> JobOut:
    return JobOut.model_validate(
        {
            **{k: getattr(job, k) for k in JobOut.model_fields if k != "trace_id"},
            "trace_id": job.payload.get("trace_id"),
        }
    )


@router.get("", responses=_ERRORS)
def list_jobs(
    session: SessionDep,
    ctx: CanMonitor,
    status: Annotated[Literal["queued", "running", "succeeded", "failed"] | None, Query()] = None,
) -> list[JobOut]:
    """The organisation's 100 newest background jobs. Platform jobs are not shown."""
    query = select(Job).where(Job.organisation_id == ctx.organisation_id)
    if status is not None:
        query = query.where(Job.status == status)
    return [job_out(j) for j in session.scalars(query.order_by(Job.created_at.desc()).limit(100))]


@router.post("/{job_id}/retry", responses=_ERRORS)
def retry_job(job_id: UUID, request: Request, session: SessionDep, ctx: CanMonitor) -> JobOut:
    """Queue a failed job again with a fresh set of attempts."""
    job = service.get_job(session, job_id)
    if job is None or job.organisation_id != ctx.organisation_id:
        raise AppError(404, "not_found", "Job not found.")
    if job.status != "failed":
        raise AppError(409, "job_not_failed", "Only a failed job can be retried.")
    service.retry(session, job)
    audit.record(
        session,
        "job.retried",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="job",
        target_id=str(job.id),
        ip_address=client_ip(request),
        detail={"kind": job.kind},
    )
    session.refresh(job)
    return job_out(job)
