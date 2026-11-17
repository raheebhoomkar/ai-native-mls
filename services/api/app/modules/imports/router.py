from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.imports import service
from app.modules.imports.fields import FIELDS
from app.modules.imports.schemas import (
    FieldOut,
    ImportedListingOut,
    ImportOut,
    ImportRequest,
    ImportSourceOut,
    PreviewOut,
)
from app.modules.organisations.deps import TenantContext, require

imports_router = APIRouter(prefix="/imports", tags=["imports"])
listing_import_router = APIRouter(prefix="/listings/{listing_id}/import-source", tags=["imports"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]


@imports_router.get("/fields", responses=_ERRORS)
def list_fields(ctx: CanWrite) -> list[FieldOut]:
    """The canonical fields an import file can hold, with the headers recognised for each."""
    return [FieldOut.model_validate(field) for field in FIELDS]


@imports_router.post("/preview", responses=_ERRORS)
def preview(body: ImportRequest, ctx: CanWrite, session: SessionDep) -> PreviewOut:
    """Check a CSV file without saving anything."""
    return PreviewOut.model_validate(service.preview(session, ctx, body.content))


@imports_router.post("", status_code=201, responses=_ERRORS)
def import_listings(
    body: ImportRequest, request: Request, ctx: CanWrite, session: SessionDep
) -> ImportOut:
    """Create a draft, private listing per row. Refused with 422 if any row has an error."""
    batch, created = service.import_file(session, ctx, body.filename, body.content)
    audit.record(
        session,
        "listing.imported",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="listing_import",
        target_id=str(batch.id),
        ip_address=client_ip(request),
        detail={"filename": batch.filename, "listings": batch.row_count},
    )
    return ImportOut(
        id=batch.id,
        filename=batch.filename,
        created_at=batch.created_at,
        listings=[
            ImportedListingOut(row_number=row.row_number, listing_id=row.listing_id, title=title)
            for row, title in created
        ],
    )


@listing_import_router.get("", responses=_ERRORS)
def get_import_source(
    listing_id: UUID, ctx: CanRead, session: SessionDep
) -> ImportSourceOut | None:
    """Which file and row created this listing. Null when it was not imported, or when the
    listing belongs to another organisation."""
    found = service.get_source(session, ctx, listing_id)
    if found is None:
        return None
    row, batch = found
    return ImportSourceOut(
        import_id=batch.id,
        filename=batch.filename,
        row_number=row.row_number,
        external_id=row.external_id,
        imported_at=batch.created_at,
        source=row.source,
    )
