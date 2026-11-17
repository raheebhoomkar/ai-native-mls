from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.auth.deps import PlatformAdmin
from app.modules.ops import service

router = APIRouter(prefix="/ops", tags=["ops"])


class JobCounts(BaseModel):
    queued: int
    overdue: int = Field(description="Queued jobs due more than 5 minutes ago.")
    running: int
    failed_recently: int = Field(description="Jobs that failed for good in the last 24 hours.")
    failed_platform: int = Field(description="Failed jobs that belong to no organisation.")
    unknown_kinds: list[str] = Field(description="Job kinds that no handler runs.")


class DeliveryCounts(BaseModel):
    pending: int
    failed_recently: int


class AiCounts(BaseModel):
    failed_recently: int
    last_error: str | None


class OpsStatusOut(BaseModel):
    """Platform-wide numbers. `alerts` says in plain words what needs an operator."""

    checked_at: datetime
    jobs: JobCounts
    webhook_deliveries: DeliveryCounts
    ai: AiCounts
    alerts: list[str]


@router.get("/status", responses={code: {"model": ErrorResponse} for code in (401, 403)})
def ops_status(session: SessionDep, _admin: PlatformAdmin) -> OpsStatusOut:
    """Background jobs, webhook deliveries and AI runs across all organisations."""
    return OpsStatusOut.model_validate(service.status(session))
