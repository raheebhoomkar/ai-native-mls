from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ApiKey(Base):
    """A key for a third-party client. It acts as the member who created it, limited to its
    scopes. Only the SHA-256 of the secret is stored; the key is shown once.
    """

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"), index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100))
    # The visible start of the key, so people can tell keys apart; not secret.
    prefix: Mapped[str] = mapped_column(String(20), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKeyUsage(Base):
    """One request made with a key, written after the response by the usage middleware.

    No foreign keys: rows are written in their own transaction, and the log must outlive
    the key.
    """

    __tablename__ = "api_key_usage"
    __table_args__ = (Index("ix_api_key_usage_key_at", "api_key_id", "at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    api_key_id: Mapped[UUID] = mapped_column()
    organisation_id: Mapped[UUID] = mapped_column(index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    status_code: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(64))


class IdempotencyRecord(Base):
    """The stored answer to a write sent with an `Idempotency-Key` header.

    `principal` is a hash of the caller's credential (API key or session cookie), so two
    callers can use the same key without seeing each other's answers.
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("principal", "key", name="uq_idempotency_principal_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    principal: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    request_hash: Mapped[str] = mapped_column(String(64))
    # None while the first request is still being handled.
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
