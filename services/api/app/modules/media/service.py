"""Media belongs to a listing. Who may read the listing may see its media; who may edit
the listing may upload and remove it. Files are served through short-lived signed URLs,
so an `<img>` tag can load them without sending API headers.
"""

import hashlib
import hmac
import secrets
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.listings import service as listings
from app.modules.listings.models import Listing
from app.modules.media.models import MediaAsset
from app.modules.media.storage import get_storage
from app.modules.organisations.deps import TenantContext

URL_TTL_SECONDS = 15 * 60

_TYPE_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}


def detect_type(data: bytes) -> str | None:
    """The file's first bytes decide its type; the declared type must agree."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def clean_filename(name: str) -> str:
    """Keep the last path part, drop control characters; display only."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:200] or "upload"


# --- Signed URLs ---------------------------------------------------------------------------


@lru_cache
def _signing_key() -> bytes:
    configured = get_settings().media_signing_key
    # shortcut: outside production a per-process key; URLs stop working after a restart.
    return configured.get_secret_value().encode() if configured else secrets.token_bytes(32)


def _signature(asset_id: UUID, expires: int) -> str:
    message = f"{asset_id}:{expires}".encode()
    return hmac.new(_signing_key(), message, hashlib.sha256).hexdigest()


def signed_url(asset_id: UUID) -> str:
    expires = int(time.time()) + URL_TTL_SECONDS
    signature = _signature(asset_id, expires)
    return f"/api/v1/media/{asset_id}/content?expires={expires}&signature={signature}"


def check_signature(asset_id: UUID, expires: int, signature: str) -> None:
    valid = hmac.compare_digest(_signature(asset_id, expires), signature)
    if not valid or expires < time.time():
        raise AppError(403, "link_expired", "This media link is invalid or has expired.")


# --- Records -------------------------------------------------------------------------------


def _not_found() -> AppError:
    return AppError(404, "not_found", "Media not found.")


def can_manage(ctx: TenantContext, listing: Listing) -> bool:
    """Upload to and remove from this listing's media."""
    return listings.can_edit(ctx, listing) and listing.archived_at is None


def _check_manage(ctx: TenantContext, listing: Listing) -> None:
    if not listings.can_edit(ctx, listing):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    if listing.archived_at is not None:
        raise AppError(409, "listing_archived", "This listing is archived.")


def upload(
    session: Session,
    ctx: TenantContext,
    listing_id: UUID,
    *,
    filename: str,
    declared_type: str,
    data: bytes,
) -> MediaAsset:
    listing = listings.get_listing(session, ctx, listing_id)  # 404 if not visible
    _check_manage(ctx, listing)
    if len(data) > get_settings().media_max_bytes:
        raise file_too_large()
    detected = detect_type(data)
    declared = _TYPE_ALIASES.get(declared_type.lower(), declared_type.lower())
    if detected is None or detected != declared:
        raise AppError(
            415,
            "unsupported_media_type",
            "Upload a JPEG, PNG or WebP image. The file's contents must match its type.",
        )

    asset_id = uuid4()
    asset = MediaAsset(
        id=asset_id,
        organisation_id=listing.organisation_id,
        listing_id=listing.id,
        uploaded_by_user_id=ctx.user.id,
        kind="original",
        status="ready",
        storage_key=f"{listing.organisation_id}/{asset_id}",
        filename=clean_filename(filename),
        content_type=detected,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    session.add(asset)
    session.flush()
    # shortcut: if the transaction fails after this, the file stays orphaned in storage;
    # add a sweep for keys with no row if that is ever seen.
    get_storage().put(asset.storage_key, data, detected)
    return asset


def file_too_large() -> AppError:
    limit_mb = get_settings().media_max_bytes / (1024 * 1024)
    return AppError(413, "file_too_large", f"Files can be at most {limit_mb:g} MB.")


def list_media(
    session: Session, ctx: TenantContext, listing_id: UUID
) -> tuple[Listing, Sequence[MediaAsset]]:
    listing = listings.get_listing(session, ctx, listing_id)  # 404 if not visible
    return listing, session.scalars(
        select(MediaAsset)
        .where(
            MediaAsset.listing_id == listing_id,
            MediaAsset.kind == "original",
            MediaAsset.deleted_at.is_(None),
        )
        .order_by(MediaAsset.created_at, MediaAsset.id)
    ).all()


def delete(session: Session, ctx: TenantContext, asset_id: UUID) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.kind != "original":
        raise _not_found()
    try:
        listing = listings.get_listing(session, ctx, asset.listing_id)
    except AppError:
        raise _not_found() from None  # same answer whether it exists or not
    _check_manage(ctx, listing)
    now = datetime.now(UTC)
    session.execute(
        update(MediaAsset)
        .where((MediaAsset.id == asset.id) | (MediaAsset.original_id == asset.id))
        .values(deleted_at=now)
    )
    session.refresh(asset)
    return asset


def get_content(session: Session, asset_id: UUID) -> tuple[MediaAsset, bytes]:
    """For a request that already passed `check_signature`."""
    asset = session.get(MediaAsset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise _not_found()
    try:
        return asset, get_storage().get(asset.storage_key)
    except FileNotFoundError:
        raise _not_found() from None
