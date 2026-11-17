from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

DELIVERY_STATUSES: tuple[str, ...] = ("pending", "succeeded", "failed")


class WebhookSubscription(Base):
    """An organisation's endpoint for events. Deliveries are signed with `secret` (HMAC-SHA256).

    The secret is kept as is, because signing needs it; it is shown to people once.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"), index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    url: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(String(200), default="")
    event_kinds: Mapped[list[str]] = mapped_column(JSONB)
    secret: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookDelivery(Base):
    """One event sent to one subscription, with every attempt's outcome summed up.

    Unique per subscription and event, so an event is never queued twice for one endpoint.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint(one_of("status", DELIVERY_STATUSES), name="ck_webhook_deliveries_status"),
        UniqueConstraint("subscription_id", "event_id", name="uq_webhook_deliveries_event"),
        Index("ix_webhook_deliveries_subscription_created", "subscription_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    subscription_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE")
    )
    # None for a test ping, which has no outbox event.
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("outbox_events.id"))
    event_kind: Mapped[str] = mapped_column(String(50))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    # The start of the endpoint's last answer, to help whoever runs it debug.
    last_response: Mapped[str | None] = mapped_column(String(500))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
