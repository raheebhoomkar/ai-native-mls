from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, one_of

KINDS: tuple[str, ...] = ("original", "thumbnail")
# Of an original: whether its derivatives are made. A thumbnail is always "ready".
STATUSES: tuple[str, ...] = ("processing", "ready", "failed")


class MediaAsset(Base):
    """One stored file. Originals are never changed; derivatives are separate rows."""

    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint(one_of("kind", KINDS), name="ck_media_assets_kind"),
        CheckConstraint(one_of("status", STATUSES), name="ck_media_assets_status"),
        CheckConstraint("size_bytes >= 0", name="ck_media_assets_size"),
        # A derivative points at its original; an original points at nothing.
        CheckConstraint(
            "(kind = 'original') = (original_id IS NULL)", name="ck_media_assets_original"
        ),
        Index("ix_media_assets_listing_created", "listing_id", "created_at"),
        Index("ix_media_assets_original", "original_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id"))
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id"))
    original_id: Mapped[UUID | None] = mapped_column(ForeignKey("media_assets.id"))
    uploaded_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    # As the uploader named it; display only, never used as a path.
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set on removal; the stored file is deleted later by a retention job (chunk 3).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
