"""Role-aware dashboard: counts from other modules, each shown only with its permission."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.collaboration import service as collaboration
from app.modules.compliance import service as compliance
from app.modules.jobs import service as jobs
from app.modules.listings import service as listings
from app.modules.organisations.deps import TenantContext, require
from app.modules.workflow import service as workflow

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class ListingCounts(BaseModel):
    organisation: dict[str, int] = Field(
        description="The organisation's listings that are not archived, by status."
    )
    mine: dict[str, int] = Field(description="Listings where you are the agent, by status.")


class DashboardOut(BaseModel):
    """A part is null when your permissions do not cover it."""

    listings: ListingCounts | None
    workflows: dict[str, int] | None = Field(description="Workflow runs by status.")
    review_queue: int | None = Field(description="Policy findings waiting for you to review.")
    failed_jobs: int | None
    unread_notifications: int


@router.get("", responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}})
def dashboard(
    session: SessionDep,
    ctx: Annotated[TenantContext, Depends(require("organisation:read"))],
) -> DashboardOut:
    can_read = ctx.has("listing:read")
    return DashboardOut(
        listings=ListingCounts(
            organisation=listings.count_by_status(session, ctx.organisation_id),
            mine=listings.count_by_status(session, ctx.organisation_id, ctx.user.id),
        )
        if can_read
        else None,
        workflows=workflow.count_by_status(session, ctx.organisation_id) if can_read else None,
        review_queue=len(compliance.queue(session, ctx)) if ctx.has("listing:publish") else None,
        failed_jobs=jobs.count_failed(session, ctx.organisation_id)
        if ctx.has("audit:read")
        else None,
        unread_notifications=collaboration.unread_count(session, ctx),
    )
