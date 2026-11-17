from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.core.pagination import PageParams, paginate
from app.modules.audit.models import AuditEvent


def record(
    session: Session,
    action: str,
    *,
    actor_user_id: UUID | None = None,
    organisation_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip_address: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the caller's transaction.

    Never put secrets (passwords, tokens) in `detail`.
    """
    event = AuditEvent(
        action=action,
        actor_user_id=actor_user_id,
        organisation_id=organisation_id,
        target_type=target_type,
        target_id=target_id,
        ip_address=ip_address,
        request_id=request_id_var.get(),
        detail=detail or {},
    )
    session.add(event)
    session.flush()
    return event


def count_recent(
    session: Session,
    action: str,
    since: datetime,
    *,
    target_id: str | None = None,
    ip_address: str | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == action, AuditEvent.occurred_at >= since)
    )
    if target_id is not None:
        stmt = stmt.where(AuditEvent.target_id == target_id)
    if ip_address is not None:
        stmt = stmt.where(AuditEvent.ip_address == ip_address)
    return session.scalar(stmt) or 0


def list_for_organisation(
    session: Session,
    organisation_id: UUID,
    page: PageParams,
    *,
    action: str | None = None,
    actor_user_id: UUID | None = None,
    target_id: str | None = None,
) -> tuple[Sequence[AuditEvent], str | None]:
    """Newest first. `action` matches a prefix, such as `listing.`."""
    stmt = select(AuditEvent).where(AuditEvent.organisation_id == organisation_id)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action, autoescape=True))
    if actor_user_id is not None:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if target_id:
        stmt = stmt.where(AuditEvent.target_id == target_id)
    return paginate(session, stmt, page, sort=AuditEvent.occurred_at, id_column=AuditEvent.id)


def list_for_listing(
    session: Session, organisation_id: UUID, listing_id: UUID, limit: int = 100
) -> Sequence[AuditEvent]:
    """Events about one listing, newest first: those that target it, and those about its
    checks and runs that name it in their detail."""
    key = str(listing_id)
    return session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.organisation_id == organisation_id,
            or_(
                (AuditEvent.target_type == "listing") & (AuditEvent.target_id == key),
                AuditEvent.detail["listing_id"].astext == key,
            ),
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    ).all()
