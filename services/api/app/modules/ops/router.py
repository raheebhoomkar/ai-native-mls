import hmac
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse
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


class RunJobsOut(BaseModel):
    ran: int = Field(description="Jobs run in this call, whatever their outcome.")


@router.get("/run-jobs", responses={code: {"model": ErrorResponse} for code in (401, 404)})
def run_jobs(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> RunJobsOut:
    """Run due background jobs for up to 50 seconds, for a scheduler such as Vercel Cron.

    Needs `Authorization: Bearer <CRON_SECRET>`. Answers 404 when `CRON_SECRET` is not set,
    since the host then runs `python -m app.worker` instead.
    """
    secret = get_settings().cron_secret
    if secret is None:
        raise AppError(404, "not_found", "Not found.")
    expected = f"Bearer {secret.get_secret_value()}".encode()
    if not hmac.compare_digest((authorization or "").encode(), expected):
        raise AppError(401, "invalid_cron_secret", "A valid cron secret is required.")
    return RunJobsOut(ran=service.run_jobs(session))
