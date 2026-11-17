from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

VALUATION_STATUSES: tuple[str, ...] = ("ok", "insufficient_data")


class Valuation(Base):
    """One estimate, kept with every assumption that produced it so it can be re-run and
    later compared with the price the listing actually sold for.
    """

    __tablename__ = "valuations"
    __table_args__ = (
        CheckConstraint(one_of("status", VALUATION_STATUSES), name="ck_valuations_status"),
        Index("ix_valuations_listing_created", "listing_id", "created_at"),
        Index("ix_valuations_organisation_created", "organisation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"))
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    model_version: Mapped[str] = mapped_column(String(40))
    simulation_version: Mapped[str] = mapped_column(String(40))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The estimate's middle and range, as columns so outcomes can be evaluated in SQL.
    estimate_low: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estimate_median: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estimate_high: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # Filled when the listing later sells (reported closed price).
    outcome_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
