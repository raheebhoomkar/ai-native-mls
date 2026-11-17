"""Property is the durable real-world asset. Listing is one time-bound offer to sell or let it.

A property can have many listings over time, so facts about the asset (address, size)
live on Property and facts about the offer (price, status, remarks) live on Listing.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

PROPERTY_TYPES: tuple[str, ...] = ("apartment", "house", "villa", "plot", "commercial", "other")
AREA_UNITS: tuple[str, ...] = ("sqft", "sqm")
LISTING_TYPES: tuple[str, ...] = ("sale", "rent")
STATUSES: tuple[str, ...] = (
    "draft",
    "pending_review",
    "active",
    "temporarily_off_market",
    "sold",
    "withdrawn",
    "expired",
)
VISIBILITIES: tuple[str, ...] = ("private", "network")


def _timestamp() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        CheckConstraint(one_of("property_type", PROPERTY_TYPES), name="ck_properties_type"),
        CheckConstraint(
            f"area_unit IS NULL OR {one_of('area_unit', AREA_UNITS)}",
            name="ck_properties_area_unit",
        ),
        # An area is meaningless without its unit, and the reverse.
        CheckConstraint(
            "(area_value IS NULL) = (area_unit IS NULL)", name="ck_properties_area_has_unit"
        ),
        Index("ix_properties_organisation_city", "organisation_id", "city"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    property_type: Mapped[str] = mapped_column(String(20))
    address_line1: Mapped[str] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    locality: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2))
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    bathrooms: Mapped[int | None] = mapped_column(Integer)
    area_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    area_unit: Mapped[str | None] = mapped_column(String(10))
    year_built: Mapped[int | None] = mapped_column(Integer)
    # Incremented on every update; a stale writer gets 409 instead of overwriting.
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {"version_id_col": version}


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint(one_of("status", STATUSES), name="ck_listings_status"),
        CheckConstraint(one_of("listing_type", LISTING_TYPES), name="ck_listings_type"),
        CheckConstraint(one_of("visibility", VISIBILITIES), name="ck_listings_visibility"),
        CheckConstraint("list_price_amount > 0", name="ck_listings_price_positive"),
        Index("ix_listings_organisation_status", "organisation_id", "status"),
        Index("ix_listings_network", "visibility", "status"),
        Index("ix_listings_created", "created_at", "id"),
        Index("ix_listings_price", "list_price_amount", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    property_id: Mapped[UUID] = mapped_column(ForeignKey("properties.id"), index=True)
    listing_agent_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    listing_type: Mapped[str] = mapped_column(String(10))
    visibility: Mapped[str] = mapped_column(String(10), default="private")
    title: Mapped[str] = mapped_column(String(200))
    remarks: Mapped[str | None] = mapped_column(Text)
    # Money is stored as an exact decimal with its currency, never as a float.
    list_price_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    list_price_currency: Mapped[str] = mapped_column(String(3))
    expires_on: Mapped[date | None] = mapped_column(Date)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Recorded by the listing agent when marking the listing sold; not independently verified.
    sold_price_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {"version_id_col": version}


class ListingStatusHistory(Base):
    """Append-only: one row per status change, including the initial draft."""

    __tablename__ = "listing_status_history"
    __table_args__ = (Index("ix_listing_status_history_listing", "listing_id", "changed_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"))
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    changed_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = _timestamp()


FEATURE_SOURCES: tuple[str, ...] = ("ai_reviewed",)


class ListingFeature(Base):
    """A confirmed observable feature (flooring, appliance...). Separate from the columns an
    agent enters, so an AI suggestion can never overwrite them. Added only by a person.
    """

    __tablename__ = "listing_features"
    __table_args__ = (
        CheckConstraint(one_of("source", FEATURE_SOURCES), name="ck_listing_features_source"),
        Index("ix_listing_features_listing", "listing_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"))
    attribute: Mapped[str] = mapped_column(String(30))
    value: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))
    # The photo that shows it, when it came from an AI suggestion.
    media_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("media_assets.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _timestamp()
