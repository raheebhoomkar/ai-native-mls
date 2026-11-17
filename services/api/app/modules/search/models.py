from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ListingVector(Base):
    """One listing's embedding for VECTOR_STORE=postgres. Rows of another model_key are
    never compared with a query; re-indexing replaces them.
    """

    __tablename__ = "listing_vectors"
    __table_args__ = (Index("ix_listing_vectors_model", "model_key"),)

    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    model_key: Mapped[str] = mapped_column(String(200))
    vector: Mapped[list[float]] = mapped_column(ARRAY(Float))
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
