from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

COMMENT_VISIBILITIES: tuple[str, ...] = ("team", "private")
NOTIFICATION_KINDS: tuple[str, ...] = ("assigned", "comment", "workflow_finished")


class ListingAssignment(Base):
    """Who in the listing's organisation is working on it now, besides the listing agent.

    One row per listing; reassigning replaces it. Earlier assignments are in the audit log.
    """

    __tablename__ = "listing_assignments"

    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(500))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Comment(Base):
    """A comment on a listing. `team`: everyone in the owning organisation who can read the
    listing. `private`: a note only its author sees. Other organisations never see either.
    """

    __tablename__ = "listing_comments"
    __table_args__ = (
        CheckConstraint(one_of("visibility", COMMENT_VISIBILITIES), name="ck_comments_visibility"),
        Index("ix_listing_comments_listing_created", "listing_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"))
    author_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    visibility: Mapped[str] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Kept, with the body cleared, so a timeline still shows that something was said.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    """An in-app message to one person in one organisation."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(one_of("kind", NOTIFICATION_KINDS), name="ck_notifications_kind"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(1000), default="")
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPreference(Base):
    """A kind someone turned off (or back on). No row means on."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_notification_preferences"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean)
