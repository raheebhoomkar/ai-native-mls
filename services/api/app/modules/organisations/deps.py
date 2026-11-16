"""Tenant scoping and permission checks. Every tenant-owned route goes through here."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from app.core.db import SessionDep
from app.core.errors import AppError
from app.modules.audit import service as audit
from app.modules.auth.deps import CurrentUser, client_ip
from app.modules.auth.models import User
from app.modules.organisations import service
from app.modules.organisations.permissions import ROLE_PERMISSIONS, Permission


@dataclass(frozen=True)
class TenantContext:
    """Who is acting and in which organisation. Services filter by `organisation_id`."""

    user: User
    organisation_id: UUID
    # None when a platform administrator acts in an organisation they do not belong to.
    role: str | None

    def has(self, permission: Permission) -> bool:
        if self.user.is_platform_admin:
            return True
        return self.role is not None and permission in ROLE_PERMISSIONS[self.role]


def _forbidden() -> AppError:
    return AppError(403, "forbidden", "You do not have permission to do this.")


def _tenant_scope(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    x_organisation_id: Annotated[
        UUID | None,
        Header(description="Organisation to act in. Optional when you belong to exactly one."),
    ] = None,
) -> TenantContext:
    memberships = service.list_memberships(session, user.id)

    if x_organisation_id is None:
        if len(memberships) == 1:
            membership, _ = memberships[0]
            return TenantContext(user, membership.organisation_id, membership.role)
        raise AppError(
            400,
            "organisation_required",
            "Send the X-Organisation-ID header to choose an organisation.",
        )

    for membership, _ in memberships:
        if membership.organisation_id == x_organisation_id:
            return TenantContext(user, membership.organisation_id, membership.role)

    organisation = service.get_organisation(session, x_organisation_id)
    if user.is_platform_admin and organisation is not None:
        return TenantContext(user, organisation.id, None)

    # Same response whether the organisation exists or not, so IDs cannot be probed.
    audit.record(
        session,
        "access.denied",
        actor_user_id=user.id,
        organisation_id=organisation.id if organisation else None,
        target_type="organisation",
        target_id=str(x_organisation_id),
        ip_address=client_ip(request),
        detail={"path": request.url.path},
    )
    session.commit()  # keep the audit event; the raise below would roll it back
    raise _forbidden()


TenantScope = Annotated[TenantContext, Depends(_tenant_scope)]


def require(permission: Permission) -> Callable[[TenantContext], TenantContext]:
    """Dependency: the caller must hold `permission` in the active organisation.

    Usage: `ctx: Annotated[TenantContext, Depends(require("member:read"))]`
    """

    def _require(ctx: TenantScope) -> TenantContext:
        if not ctx.has(permission):
            raise _forbidden()
        return ctx

    return _require
