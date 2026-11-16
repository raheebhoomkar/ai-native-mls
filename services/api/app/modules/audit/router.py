from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParamsDep
from app.modules.audit import service
from app.modules.organisations.deps import TenantContext, require

router = APIRouter(prefix="/audit-events", tags=["audit"])


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    organisation_id: UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    request_id: str | None
    detail: dict[str, Any]


@router.get("", responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}})
def list_audit_events(
    session: SessionDep,
    ctx: Annotated[TenantContext, Depends(require("audit:read"))],
    page: PageParamsDep,
) -> Page[AuditEventOut]:
    """Audit events of the active organisation, newest first."""
    items, next_cursor = service.list_for_organisation(session, ctx.organisation_id, page)
    return Page(
        items=[AuditEventOut.model_validate(item) for item in items], next_cursor=next_cursor
    )
