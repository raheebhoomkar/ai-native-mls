from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse
from app.core.pagination import Page, PageParamsDep
from app.modules.audit import service as audit
from app.modules.auth import service as auth
from app.modules.auth.deps import CurrentUser, PlatformAdmin, client_ip
from app.modules.organisations import service
from app.modules.organisations.deps import TenantContext, require
from app.modules.organisations.models import Organisation
from app.modules.organisations.permissions import ALLOWED_ROLES
from app.modules.organisations.schemas import (
    CurrentOrganisationOut,
    InvitationAccept,
    InvitationAccepted,
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
    InvitationPreview,
    InvitationToken,
    MemberOut,
    OrganisationCreate,
    OrganisationOut,
    RoleChange,
)

router = APIRouter(prefix="/organisations", tags=["organisations"])
# Reached from an invitation link by someone who may not have an account yet.
public_router = APIRouter(prefix="/invitations", tags=["invitations"])

_DENIED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}
_BAD_LINK: dict[int | str, dict[str, Any]] = {400: {"model": ErrorResponse}}

CanRead = Annotated[TenantContext, Depends(require("organisation:read"))]
CanReadMembers = Annotated[TenantContext, Depends(require("member:read"))]
CanManageMembers = Annotated[TenantContext, Depends(require("member:manage"))]


def _organisation(session: Session, ctx: TenantContext) -> Organisation:
    organisation = service.get_organisation(session, ctx.organisation_id)
    if organisation is None:
        raise AppError(404, "not_found", "Organisation not found.")
    return organisation


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
def get_current_organisation(session: SessionDep, ctx: CanRead) -> CurrentOrganisationOut:
    """The organisation selected by `X-Organisation-ID`, with your role and permissions in it."""
    organisation = _organisation(session, ctx)
    return CurrentOrganisationOut(
        id=organisation.id,
        name=organisation.name,
        kind=organisation.kind,
        created_at=organisation.created_at,
        my_role=ctx.role,
        my_permissions=sorted(ctx.permissions),
        assignable_roles=list(ALLOWED_ROLES[organisation.kind]),
    )


@router.get("/current/members", responses=_DENIED)
def list_members(session: SessionDep, ctx: CanReadMembers, page: PageParamsDep) -> Page[MemberOut]:
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


@router.patch("/current/members/{user_id}", status_code=204, responses=_DENIED)
def change_member_role(
    user_id: UUID, body: RoleChange, request: Request, session: SessionDep, ctx: CanManageMembers
) -> None:
    """Change a member's role. You cannot change your own."""
    membership, previous = service.change_role(
        session, _organisation(session, ctx), user_id=user_id, role=body.role, actor=ctx.user
    )
    audit.record(
        session,
        "member.role_changed",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="user",
        target_id=str(user_id),
        ip_address=client_ip(request),
        detail={"from": previous, "to": membership.role},
    )


@router.delete("/current/members/{user_id}", status_code=204, responses=_DENIED)
def remove_member(
    user_id: UUID, request: Request, session: SessionDep, ctx: CanManageMembers
) -> None:
    """Remove a member from the organisation. Their account is kept. You cannot remove yourself."""
    membership = service.remove_member(
        session, ctx.organisation_id, user_id=user_id, actor=ctx.user
    )
    audit.record(
        session,
        "member.removed",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="user",
        target_id=str(user_id),
        ip_address=client_ip(request),
        detail={"role": membership.role},
    )


@router.get("/current/invitations", responses=_DENIED)
def list_invitations(
    session: SessionDep, ctx: CanManageMembers, page: PageParamsDep
) -> Page[InvitationOut]:
    """Pending invitations. Accepted, revoked and expired ones are not listed."""
    items, next_cursor = service.list_pending_invitations(session, ctx.organisation_id, page)
    return Page(
        items=[InvitationOut.model_validate(item) for item in items], next_cursor=next_cursor
    )


@router.post("/current/invitations", status_code=201, responses=_DENIED)
def create_invitation(
    body: InvitationCreate, request: Request, session: SessionDep, ctx: CanManageMembers
) -> InvitationCreated:
    """Invite a person by email. The response is the only time the link token is available.

    No email is sent: share the link yourself.
    """
    invitation, token = service.create_invitation(
        session, _organisation(session, ctx), email=body.email, role=body.role, invited_by=ctx.user
    )
    audit.record(
        session,
        "invitation.created",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="invitation",
        target_id=str(invitation.id),
        ip_address=client_ip(request),
        detail={"email": invitation.email, "role": invitation.role},
    )
    return InvitationCreated(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        token=token,
    )


@router.delete("/current/invitations/{invitation_id}", status_code=204, responses=_DENIED)
def revoke_invitation(
    invitation_id: UUID, request: Request, session: SessionDep, ctx: CanManageMembers
) -> None:
    invitation = service.revoke_invitation(session, ctx.organisation_id, invitation_id)
    audit.record(
        session,
        "invitation.revoked",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="invitation",
        target_id=str(invitation.id),
        ip_address=client_ip(request),
        detail={"email": invitation.email},
    )


# The token travels in the request body, not the URL, so it stays out of access logs.
@public_router.post("/preview", responses=_BAD_LINK)
def preview_invitation(body: InvitationToken, session: SessionDep) -> InvitationPreview:
    """What an invitation link offers. Public: the link token is the credential."""
    invitation, organisation = service.find_invitation(session, body.token)
    return InvitationPreview(
        organisation_name=organisation.name,
        email=invitation.email,
        role=invitation.role,
        account_exists=auth.get_user_by_email(session, invitation.email) is not None,
    )


@public_router.post("/accept", responses=_BAD_LINK)
def accept_invitation(
    body: InvitationAccept, request: Request, session: SessionDep
) -> InvitationAccepted:
    """Join the organisation. Send `full_name` and `password` if the email has no account yet.

    Does not sign you in.
    """
    invitation, user, created = service.accept_invitation(
        session, token=body.token, full_name=body.full_name, password=body.password
    )
    ip = client_ip(request)
    if created:
        audit.record(
            session,
            "user.created",
            actor_user_id=user.id,
            organisation_id=invitation.organisation_id,
            target_type="user",
            target_id=str(user.id),
            ip_address=ip,
            detail={"via": "invitation"},
        )
    audit.record(
        session,
        "invitation.accepted",
        actor_user_id=user.id,
        organisation_id=invitation.organisation_id,
        target_type="invitation",
        target_id=str(invitation.id),
        ip_address=ip,
        detail={"role": invitation.role},
    )
    organisation = service.get_organisation(session, invitation.organisation_id)
    return InvitationAccepted(
        organisation_name=organisation.name if organisation else "",
        email=user.email,
        account_created=created,
    )
