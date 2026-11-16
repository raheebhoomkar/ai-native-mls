from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.media import service
from app.modules.media.models import MediaAsset
from app.modules.organisations.deps import TenantContext, require

listing_media_router = APIRouter(prefix="/listings/{listing_id}/media", tags=["media"])
media_router = APIRouter(prefix="/media", tags=["media"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 415)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]


class MediaOut(BaseModel):
    id: UUID
    listing_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    error: str | None
    created_at: datetime
    # Signed and short-lived; fetch the list again for fresh links.
    url: str
    can_delete: bool


def _out(asset: MediaAsset, *, can_delete: bool) -> MediaOut:
    return MediaOut(
        id=asset.id,
        listing_id=asset.listing_id,
        filename=asset.filename,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        sha256=asset.sha256,
        status=asset.status,
        error=asset.error,
        created_at=asset.created_at,
        url=service.signed_url(asset.id),
        can_delete=can_delete,
    )


async def _body(request: Request, content_length: Annotated[int | None, Header()] = None) -> bytes:
    """Read the raw request body, stopping as soon as it passes the size limit."""
    limit = get_settings().media_max_bytes
    if content_length is not None and content_length > limit:
        raise service.file_too_large()
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise service.file_too_large()
    return bytes(data)


@listing_media_router.get("", responses=_ERRORS)
def list_listing_media(listing_id: UUID, ctx: CanRead, session: SessionDep) -> list[MediaOut]:
    listing, assets = service.list_media(session, ctx, listing_id)
    manage = service.can_manage(ctx, listing)
    return [_out(asset, can_delete=manage) for asset in assets]


@listing_media_router.post(
    "",
    status_code=201,
    responses=_ERRORS,
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "The file itself as the raw body, not a multipart form.",
            "content": {
                content_type: {"schema": {"type": "string", "format": "binary"}}
                for content_type in ("image/jpeg", "image/png", "image/webp")
            },
        }
    },
)
def upload_media(
    listing_id: UUID,
    request: Request,
    ctx: CanWrite,
    session: SessionDep,
    data: Annotated[bytes, Depends(_body)],
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    content_type: Annotated[str, Header()] = "",
) -> MediaOut:
    """Upload one image to a listing. Send `Content-Type` and the file name."""
    asset = service.upload(
        session, ctx, listing_id, filename=filename, declared_type=content_type, data=data
    )
    audit.record(
        session,
        "media.uploaded",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="media",
        target_id=str(asset.id),
        ip_address=client_ip(request),
        detail={"listing_id": str(listing_id), "size_bytes": asset.size_bytes},
    )
    return _out(asset, can_delete=True)


@media_router.delete("/{asset_id}", status_code=204, responses=_ERRORS)
def delete_media(asset_id: UUID, request: Request, ctx: CanWrite, session: SessionDep) -> None:
    asset = service.delete(session, ctx, asset_id)
    audit.record(
        session,
        "media.deleted",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="media",
        target_id=str(asset.id),
        ip_address=client_ip(request),
        detail={"listing_id": str(asset.listing_id)},
    )


@media_router.get(
    "/{asset_id}/content",
    response_class=Response,
    responses={
        200: {"content": {"image/*": {}}},
        **{code: {"model": ErrorResponse} for code in (403, 404)},
    },
)
def media_content(
    asset_id: UUID,
    session: SessionDep,
    expires: Annotated[int, Query()],
    signature: Annotated[str, Query(max_length=64)],
) -> Response:
    """The file. Needs no session: the signed link from the media list is the permission."""
    service.check_signature(asset_id, expires, signature)
    asset, data = service.get_content(session, asset_id)
    return Response(
        content=data,
        media_type=asset.content_type,
        headers={
            "Cache-Control": "private, max-age=600",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        },
    )
