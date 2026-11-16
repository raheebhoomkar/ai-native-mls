from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse
from app.core.pagination import Page, PageParamsDep
from app.modules.audit import service as audit
from app.modules.auth import service as auth
from app.modules.auth.deps import CurrentUser, PlatformAdmin, client_ip
from app.modules.organisations import service
from app.modules.organisations.deps import TenantContext, require
from app.modules.organisations.schemas import MemberOut, OrganisationCreate, OrganisationOut

router = APIRouter(prefix="/organisations", tags=["organisations"])

_DENIED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}


@router.get("", responses={401: {"model": ErrorResponse}})
def list_organisations(
    session: SessionDep, user: CurrentUser, page: PageParamsDep
) -> Page[OrganisationOut]:
    """Organisations you belong to. Platform administrators see all organisations."""
    items, next_cursor = service.list_organisations(
        session, page, member_user_id=None if user.is_platform_admin else user.id
    )
    return Page(
        items=[OrganisationOut.model_validate(item) for item in items], next_cursor=next_cursor
    )


@router.post("", status_code=201, responses=_DENIED)
def create_organisation(
    body: OrganisationCreate, request: Request, session: SessionDep, admin: PlatformAdmin
) -> OrganisationOut:
    """Platform administrators only."""
    organisation = service.create_organisation(session, name=body.name, kind=body.kind)
    audit.record(
        session,
        "organisation.created",
        actor_user_id=admin.id,
        organisation_id=organisation.id,
        target_type="organisation",
        target_id=str(organisation.id),
        ip_address=client_ip(request),
    )
    return OrganisationOut.model_validate(organisation)


@router.get("/current", responses=_DENIED)
def get_current_organisation(
    session: SessionDep,
    ctx: Annotated[TenantContext, Depends(require("organisation:read"))],
) -> OrganisationOut:
    """The organisation selected by `X-Organisation-ID`."""
    organisation = service.get_organisation(session, ctx.organisation_id)
    if organisation is None:
        raise AppError(404, "not_found", "Organisation not found.")
    return OrganisationOut.model_validate(organisation)


@router.get("/current/members", responses=_DENIED)
def list_members(
    session: SessionDep,
    ctx: Annotated[TenantContext, Depends(require("member:read"))],
    page: PageParamsDep,
) -> Page[MemberOut]:
    memberships, next_cursor = service.list_members(session, ctx.organisation_id, page)
    users = auth.get_users(session, [membership.user_id for membership in memberships])
    return Page(
        items=[
            MemberOut(
                user_id=membership.user_id,
                email=users[membership.user_id].email,
                full_name=users[membership.user_id].full_name,
                role=membership.role,
                joined_at=membership.created_at,
            )
            for membership in memberships
        ],
        next_cursor=next_cursor,
    )
