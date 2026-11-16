from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
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
    session: Session, organisation_id: UUID, page: PageParams
) -> tuple[Sequence[AuditEvent], str | None]:
    stmt = select(AuditEvent).where(AuditEvent.organisation_id == organisation_id)
    return paginate(session, stmt, page, sort=AuditEvent.occurred_at, id_column=AuditEvent.id)
