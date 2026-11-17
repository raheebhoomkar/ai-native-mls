from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.auth.service import get_users
from app.modules.collaboration import service
from app.modules.collaboration.models import Comment, ListingAssignment, Notification
from app.modules.organisations.deps import TenantContext, require

listing_router = APIRouter(prefix="/listings/{listing_id}", tags=["collaboration"])
comments_router = APIRouter(prefix="/comments", tags=["collaboration"])
notifications_router = APIRouter(prefix="/notifications", tags=["collaboration"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 422)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
Member = Annotated[TenantContext, Depends(require("organisation:read"))]

Body = Annotated[str, Field(min_length=1, max_length=5000)]


class AssignmentIn(BaseModel):
    user_id: UUID | None = Field(description="Null clears the assignment.")
    note: Annotated[str, Field(max_length=500)] | None = None


class AssignmentOut(BaseModel):
    user_id: UUID
    user_name: str
    assigned_by_user_id: UUID
    note: str | None
    assigned_at: datetime


class CommentIn(BaseModel):
    body: Body
    visibility: Literal["team", "private"] = "team"


class CommentEditIn(BaseModel):
    body: Body


class CommentOut(BaseModel):
    id: UUID
    listing_id: UUID
    author_user_id: UUID
    author_name: str
    visibility: str
    body: str
    created_at: datetime
    edited_at: datetime | None
    deleted_at: datetime | None


class ActivityOut(BaseModel):
    at: datetime
    kind: str
    action: str
    actor_name: str | None
    summary: str
    comment_id: UUID | None
    visibility: str | None


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str
    listing_id: UUID | None
    created_at: datetime
    read_at: datetime | None


class NotificationsOut(BaseModel):
    items: list[NotificationOut]
    unread: int


def _assignment_out(session: Session, row: ListingAssignment | None) -> AssignmentOut | None:
    if row is None:
        return None
    user = get_users(session, [row.user_id])[row.user_id]
    return AssignmentOut(
        user_id=row.user_id,
        user_name=user.full_name,
        assigned_by_user_id=row.assigned_by_user_id,
        note=row.note,
        assigned_at=row.assigned_at,
    )


def _comments_out(session: Session, comments: list[Comment]) -> list[CommentOut]:
    users = get_users(session, list({c.author_user_id for c in comments}))
    return [
        CommentOut.model_validate(
            {
                **{k: getattr(c, k) for k in CommentOut.model_fields if k != "author_name"},
                "author_name": users[c.author_user_id].full_name,
            }
        )
        for c in comments
    ]


@listing_router.get("/assignment", responses=_ERRORS)
def get_assignment(listing_id: UUID, session: SessionDep, ctx: CanRead) -> AssignmentOut | None:
    listing = service.own_listing(session, ctx, listing_id)
    return _assignment_out(session, service.get_assignment(session, listing.id))


@listing_router.put("/assignment", responses=_ERRORS)
def put_assignment(
    listing_id: UUID, body: AssignmentIn, request: Request, session: SessionDep, ctx: CanRead
) -> AssignmentOut | None:
    """Assign the listing to a teammate (they are notified), or clear it. Editors only."""
    row = service.assign(session, ctx, listing_id, body.user_id, body.note)
    audit.record(
        session,
        "listing.assigned",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="listing",
        target_id=str(listing_id),
        ip_address=client_ip(request),
        detail={"user_id": str(body.user_id) if body.user_id else None},
    )
    return _assignment_out(session, row)


@listing_router.get("/comments", responses=_ERRORS)
def list_comments(listing_id: UUID, session: SessionDep, ctx: CanRead) -> list[CommentOut]:
    """Team comments and your own private notes, oldest first. Owning organisation only."""
    return _comments_out(session, list(service.list_comments(session, ctx, listing_id)))


@listing_router.post("/comments", status_code=201, responses=_ERRORS)
def add_comment(listing_id: UUID, body: CommentIn, session: SessionDep, ctx: CanRead) -> CommentOut:
    """Comment for the team (the listing agent, the assignee and earlier commenters are
    notified) or write a private note only you see."""
    comment = service.add_comment(session, ctx, listing_id, body.body, body.visibility)
    return _comments_out(session, [comment])[0]


@listing_router.get("/activity", responses=_ERRORS)
def listing_activity(listing_id: UUID, session: SessionDep, ctx: CanRead) -> list[ActivityOut]:
    """What happened to the listing, newest first: changes, checks, runs and comments."""
    return [
        ActivityOut.model_validate(item, from_attributes=True)
        for item in service.activity(session, ctx, listing_id)
    ]


@comments_router.patch("/{comment_id}", responses=_ERRORS)
def edit_comment(
    comment_id: UUID, body: CommentEditIn, session: SessionDep, ctx: CanRead
) -> CommentOut:
    """Authors only."""
    return _comments_out(session, [service.edit_comment(session, ctx, comment_id, body.body)])[0]


@comments_router.delete("/{comment_id}", status_code=204, responses=_ERRORS)
def delete_comment(comment_id: UUID, session: SessionDep, ctx: CanRead) -> None:
    """Authors only. The timeline keeps a "deleted a comment" entry without the text."""
    service.delete_comment(session, ctx, comment_id)


def _notification_out(row: Notification) -> NotificationOut:
    return NotificationOut.model_validate(row, from_attributes=True)


@notifications_router.get("", responses=_ERRORS)
def list_notifications(
    session: SessionDep, ctx: Member, unread: Annotated[bool, Query()] = False
) -> NotificationsOut:
    """Your 50 newest notifications in this organisation, and how many are unread."""
    rows, count = service.list_notifications(session, ctx, unread)
    return NotificationsOut(items=[_notification_out(r) for r in rows], unread=count)


@notifications_router.post("/{notification_id}/read", status_code=204, responses=_ERRORS)
def read_notification(notification_id: UUID, session: SessionDep, ctx: Member) -> None:
    service.mark_read(session, ctx, notification_id)


@notifications_router.post("/read-all", status_code=204, responses=_ERRORS)
def read_all(session: SessionDep, ctx: Member) -> None:
    service.mark_read(session, ctx, None)


@notifications_router.get("/preferences", responses=_ERRORS)
def get_preferences(session: SessionDep, ctx: Member) -> dict[str, bool]:
    """Each notification kind and whether you get it."""
    return service.preferences(session, ctx.user.id)


@notifications_router.put("/preferences", responses=_ERRORS)
def put_preferences(body: dict[str, bool], session: SessionDep, ctx: Member) -> dict[str, bool]:
    """Turn kinds on or off, for example `{"comment": false}`."""
    return service.set_preferences(session, ctx.user.id, body)
