"""Provenance of imported listings: which file, which row, and the original cell values."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ListingImport(Base):
    __tablename__ = "listing_imports"
    __table_args__ = (Index("ix_listing_imports_organisation", "organisation_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    imported_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    # As the uploader named it; display only.
    filename: Mapped[str] = mapped_column(String(200))
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListingImportRow(Base):
    """One per listing an import created."""

    __tablename__ = "listing_import_rows"
    __table_args__ = (
        # NULLs are distinct in Postgres, so rows without an ID never clash.
        UniqueConstraint(
            "organisation_id", "external_id", name="uq_listing_import_rows_external_id"
        ),
        Index("ix_listing_import_rows_import", "import_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    import_id: Mapped[UUID] = mapped_column(ForeignKey("listing_imports.id"))
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    row_number: Mapped[int] = mapped_column(Integer)
    external_id: Mapped[str | None] = mapped_column(String(100))
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"), unique=True)
    property_id: Mapped[UUID] = mapped_column(ForeignKey("properties.id"))
    # The original cells of the recognised columns, by header.
    source: Mapped[dict[str, Any]] = mapped_column(JSONB)
