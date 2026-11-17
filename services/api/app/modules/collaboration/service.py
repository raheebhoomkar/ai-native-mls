"""Working on a listing together: assignment, comments and private notes, notifications,
and the listing's activity timeline. Only the organisation that owns a listing sees any of it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.auth.service import get_users
from app.modules.collaboration.models import (
    NOTIFICATION_KINDS,
    Comment,
    ListingAssignment,
    Notification,
    NotificationPreference,
)
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.listings.models import Listing
from app.modules.organisations import service as organisations
from app.modules.organisations.deps import TenantContext
from app.modules.organisations.permissions import ROLE_PERMISSIONS
from app.modules.outbox import service as outbox
from app.modules.outbox.models import OutboxEvent
from app.modules.workflow.models import WorkflowRun

outbox.subscribe("workflow.finished", "collaboration.workflow_finished")


def _now() -> datetime:
    return datetime.now(UTC)


def own_listing(session: Session, ctx: TenantContext, listing_id: UUID) -> Listing:
    """The listing, if the caller may read it and their organisation owns it; else 404."""
    listing = listings.get_listing(session, ctx, listing_id)
    if listing.organisation_id != ctx.organisation_id:
        raise AppError(404, "not_found", "Listing not found.")
    return listing


# --- Notifications -------------------------------------------------------------------------


def wants(session: Session, user_id: UUID, kind: str) -> bool:
    pref = session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id, NotificationPreference.kind == kind
        )
    )
    return pref is None or pref.enabled


def notify(
    session: Session,
    user_ids: set[UUID],
    *,
    organisation_id: UUID,
    kind: str,
    title: str,
    body: str = "",
    listing_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> None:
    """Tell each person once, unless they acted themselves or turned this kind off."""
    for user_id in user_ids - {actor_id}:
        if organisations.get_membership(session, organisation_id, user_id) is None:
            continue  # left the organisation
        if not wants(session, user_id, kind):
            continue
        session.add(
            Notification(
                user_id=user_id,
                organisation_id=organisation_id,
                kind=kind,
                title=title[:200],
                body=body[:1000],
                listing_id=listing_id,
                created_at=_now(),
            )
        )
    session.flush()


def list_notifications(
    session: Session, ctx: TenantContext, unread_only: bool
) -> tuple[Sequence[Notification], int]:
    mine = (Notification.user_id == ctx.user.id) & (
        Notification.organisation_id == ctx.organisation_id
    )
    query = select(Notification).where(mine)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = session.scalars(query.order_by(Notification.created_at.desc()).limit(50)).all()
    unread = len(
        session.scalars(select(Notification.id).where(mine, Notification.read_at.is_(None))).all()
    )
    return rows, unread


def mark_read(session: Session, ctx: TenantContext, notification_id: UUID | None) -> None:
    """One notification, or all of the caller's in this organisation when the ID is None."""
    stmt = update(Notification).where(
        Notification.user_id == ctx.user.id,
        Notification.organisation_id == ctx.organisation_id,
        Notification.read_at.is_(None),
    )
    if notification_id is not None:
        row = session.get(Notification, notification_id)
        if row is None or row.user_id != ctx.user.id:
            raise AppError(404, "not_found", "Notification not found.")
        stmt = stmt.where(Notification.id == notification_id)
    session.execute(stmt.values(read_at=_now()).execution_options(synchronize_session=False))


def preferences(session: Session, user_id: UUID) -> dict[str, bool]:
    return {kind: wants(session, user_id, kind) for kind in NOTIFICATION_KINDS}


def set_preferences(session: Session, user_id: UUID, values: dict[str, bool]) -> dict[str, bool]:
    unknown = sorted(set(values) - set(NOTIFICATION_KINDS))
    if unknown:
        raise AppError(
            422, "validation_error", f"Unknown notification kind(s): {', '.join(unknown)}."
        )
    for kind, enabled in values.items():
        pref = session.scalar(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id, NotificationPreference.kind == kind
            )
        )
        if pref is None:
            session.add(NotificationPreference(user_id=user_id, kind=kind, enabled=enabled))
        else:
            pref.enabled = enabled
    session.flush()
    return preferences(session, user_id)


@jobs.handler("collaboration.workflow_finished")
def workflow_finished(session: Session, job: Job) -> None:
    """Tell whoever started a workflow run how it ended. Idempotent per event."""
    event = session.get(OutboxEvent, UUID(job.payload["event_id"]))
    if event is None:
        return
    listing = session.get(Listing, event.subject_id)
    run_id = event.payload.get("run_id")
    status = event.payload.get("status", "finished")
    if listing is None or run_id is None:
        return
    already = session.scalar(
        select(Notification.id).where(
            Notification.kind == "workflow_finished",
            Notification.body.contains(f"Run {run_id}"),
        )
    )
    if already is not None:
        return
    run = session.get(WorkflowRun, UUID(run_id))
    if run is None:
        return
    notify(
        session,
        {run.requested_by_user_id},
        organisation_id=listing.organisation_id,
        kind="workflow_finished",
        title=f"Workflow {status}: {listing.title}",
        body=f"Run {run_id} ended with status {status}.",
        listing_id=listing.id,
    )


# --- Assignment ----------------------------------------------------------------------------


def get_assignment(session: Session, listing_id: UUID) -> ListingAssignment | None:
    return session.get(ListingAssignment, listing_id)


def assign(
    session: Session, ctx: TenantContext, listing_id: UUID, user_id: UUID | None, note: str | None
) -> ListingAssignment | None:
    """Assign the listing to a member who may work on listings, or clear it (None).
    The listing's editors may do this."""
    listing = own_listing(session, ctx, listing_id)
    if not listings.can_edit(ctx, listing):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    current = get_assignment(session, listing.id)
    if user_id is None:
        if current is not None:
            session.delete(current)
            session.flush()
        return None
    membership = organisations.get_membership(session, listing.organisation_id, user_id)
    if membership is None or "listing:write" not in ROLE_PERMISSIONS[membership.role]:
        raise AppError(
            422, "validation_error", "Assign the listing to a member who works on listings."
        )
    if current is None:
        current = ListingAssignment(listing_id=listing.id, user_id=user_id)
        session.add(current)
    current.user_id = user_id
    current.assigned_by_user_id = ctx.user.id
    current.note = (note or "").strip() or None
    current.assigned_at = _now()
    session.flush()
    notify(
        session,
        {user_id},
        organisation_id=listing.organisation_id,
        kind="assigned",
        title=f"{ctx.user.full_name} assigned you: {listing.title}",
        body=current.note or "",
        listing_id=listing.id,
        actor_id=ctx.user.id,
    )
    return current


# --- Comments ------------------------------------------------------------------------------


def _visible_comments(ctx: TenantContext) -> Any:
    return or_(Comment.visibility == "team", Comment.author_user_id == ctx.user.id)


def list_comments(session: Session, ctx: TenantContext, listing_id: UUID) -> Sequence[Comment]:
    listing = own_listing(session, ctx, listing_id)
    return session.scalars(
        select(Comment)
        .where(Comment.listing_id == listing.id, _visible_comments(ctx))
        .order_by(Comment.created_at, Comment.id)
    ).all()


def add_comment(
    session: Session, ctx: TenantContext, listing_id: UUID, body: str, visibility: str
) -> Comment:
    listing = own_listing(session, ctx, listing_id)
    if not ctx.has("listing:write"):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    comment = Comment(
        organisation_id=listing.organisation_id,
        listing_id=listing.id,
        author_user_id=ctx.user.id,
        visibility=visibility,
        body=body.strip(),
        created_at=_now(),
    )
    session.add(comment)
    session.flush()
    if visibility == "team":
        assignment = get_assignment(session, listing.id)
        people = {listing.listing_agent_user_id} | ({assignment.user_id} if assignment else set())
        # Everyone who already took part in the conversation hears about the reply.
        people |= set(
            session.scalars(
                select(Comment.author_user_id).where(
                    Comment.listing_id == listing.id, Comment.visibility == "team"
                )
            )
        )
        notify(
            session,
            people,
            organisation_id=listing.organisation_id,
            kind="comment",
            title=f"{ctx.user.full_name} commented on {listing.title}",
            body=comment.body[:300],
            listing_id=listing.id,
            actor_id=ctx.user.id,
        )
    return comment


def _own_comment(session: Session, ctx: TenantContext, comment_id: UUID) -> Comment:
    comment = session.get(Comment, comment_id)
    if (
        comment is None
        or comment.organisation_id != ctx.organisation_id
        or comment.deleted_at is not None
        or not (comment.visibility == "team" or comment.author_user_id == ctx.user.id)
    ):
        raise AppError(404, "not_found", "Comment not found.")
    own_listing(session, ctx, comment.listing_id)
    if comment.author_user_id != ctx.user.id:
        raise AppError(403, "forbidden", "Only the author can change a comment.")
    return comment


def edit_comment(session: Session, ctx: TenantContext, comment_id: UUID, body: str) -> Comment:
    comment = _own_comment(session, ctx, comment_id)
    comment.body = body.strip()
    comment.edited_at = _now()
    session.flush()
    return comment


def delete_comment(session: Session, ctx: TenantContext, comment_id: UUID) -> Comment:
    comment = _own_comment(session, ctx, comment_id)
    comment.body = ""
    comment.deleted_at = _now()
    session.flush()
    return comment


# --- Activity timeline ---------------------------------------------------------------------


@dataclass
class ActivityItem:
    at: datetime
    kind: str  # "event" or "comment"
    action: str
    actor_name: str | None
    summary: str
    comment_id: UUID | None = None
    visibility: str | None = None


_SUMMARIES: dict[str, str] = {
    "listing.created": "created the listing",
    "listing.updated": "edited the listing",
    "listing.status_changed": "changed the status",
    "listing.archived": "archived the listing",
    "listing.assigned": "changed who the listing is assigned to",
    "workflow.started": "started the workflow",
    "workflow.cancelled": "cancelled the workflow",
    "workflow.retried": "retried the workflow",
    "compliance.scan_requested": "asked for a policy check",
    "compliance.finding_decided": "decided on a policy finding",
    "compliance.finding_appealed": "appealed a policy finding",
    "compliance.appeal_decided": "ruled on an appeal",
    "valuation.requested": "asked for a valuation",
    "ai.extraction_requested": "asked the AI to read the photos",
    "ai.suggestion_decided": "decided on a photo suggestion",
}


def _summary(action: str, detail: dict[str, Any]) -> str:
    text = _SUMMARIES.get(action, action)
    if action == "listing.status_changed" and "from" in detail:
        text = f"changed the status from {detail['from']} to {detail['to']}"
    elif action == "listing.updated" and isinstance(detail.get("changes"), dict):
        text = f"edited {', '.join(sorted(detail['changes']))}"
    return text


def activity(session: Session, ctx: TenantContext, listing_id: UUID) -> list[ActivityItem]:
    """Newest first: audit events about the listing and the comments the caller may see."""
    listing = own_listing(session, ctx, listing_id)
    events = audit.list_for_listing(session, listing.organisation_id, listing.id)
    comments = list_comments(session, ctx, listing.id)
    users = get_users(
        session,
        list(
            {e.actor_user_id for e in events if e.actor_user_id}
            | {c.author_user_id for c in comments}
        ),
    )

    def name(user_id: UUID | None) -> str | None:
        user: User | None = users.get(user_id) if user_id else None
        return user.full_name if user else None

    items = [
        ActivityItem(
            e.occurred_at, "event", e.action, name(e.actor_user_id), _summary(e.action, e.detail)
        )
        for e in events
    ] + [
        ActivityItem(
            c.created_at,
            "comment",
            "comment.deleted" if c.deleted_at else "comment.added",
            name(c.author_user_id),
            "deleted a comment" if c.deleted_at else c.body,
            c.id,
            c.visibility,
        )
        for c in comments
    ]
    return sorted(items, key=lambda item: item.at, reverse=True)
