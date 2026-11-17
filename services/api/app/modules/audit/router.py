from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParamsDep
from app.modules.audit import service
from app.modules.auth.service import get_users
from app.modules.organisations.deps import TenantContext, require

router = APIRouter(prefix="/audit-events", tags=["audit"])


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_name: str | None = None
    actor_email: str | None = None
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
    action: Annotated[
        str | None, Query(max_length=100, description="Action prefix, such as `listing.`.")
    ] = None,
    actor_user_id: Annotated[UUID | None, Query()] = None,
    target_id: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[AuditEventOut]:
    """Audit events of the active organisation, newest first."""
    items, next_cursor = service.list_for_organisation(
        session,
        ctx.organisation_id,
        page,
        action=action,
        actor_user_id=actor_user_id,
        target_id=target_id,
    )
    actors = get_users(session, [i.actor_user_id for i in items if i.actor_user_id])
    out = []
    for item in items:
        event = AuditEventOut.model_validate(item)
        actor = actors.get(item.actor_user_id) if item.actor_user_id else None
        if actor is not None:
            event.actor_name, event.actor_email = actor.full_name, actor.email
        out.append(event)
    return Page(items=out, next_cursor=next_cursor)
