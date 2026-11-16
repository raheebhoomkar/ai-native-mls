from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.organisations.permissions import ORGANISATION_KINDS, ROLES


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Organisation(Base):
    """The tenant. A brokerage or an MLS operator; tenant-owned rows carry its id."""

    __tablename__ = "organisations"
    __table_args__ = (
        CheckConstraint(_one_of("kind", ORGANISATION_KINDS), name="ck_organisations_kind"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    # shortcut: one role per user per organisation,
    # upgrade to a roles table if the company needs several roles in one organisation.
    __tablename__ = "organisation_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organisation_id", name="uq_memberships_user_organisation"),
        CheckConstraint(_one_of("role", ROLES), name="ck_memberships_role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
