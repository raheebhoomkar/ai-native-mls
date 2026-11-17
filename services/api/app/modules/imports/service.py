from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorDetail
from app.modules.imports.models import ListingImport, ListingImportRow
from app.modules.imports.validation import ParsedFile, parse
from app.modules.listings import service as listings
from app.modules.media.service import clean_filename
from app.modules.organisations.deps import TenantContext

# Enough to act on; the preview lists every error.
_MAX_ERROR_DETAILS = 50


def preview(session: Session, ctx: TenantContext, content: str) -> ParsedFile:
    parsed = parse(content)
    ids = {row.external_id for row in parsed.rows if row.external_id}
    if not ids:
        return parsed
    found = session.scalars(
        select(ListingImportRow.external_id).where(
            ListingImportRow.organisation_id == ctx.organisation_id,
            ListingImportRow.external_id.in_(ids),
        )
    )
    existing = {external_id for external_id in found if external_id}
    return parse(content, existing) if existing else parsed


def _invalid(parsed: ParsedFile) -> AppError:
    problems = [(f"file.{p.field}", p.message) for p in parsed.errors] + [
        (f"row {row.number}.{p.field}", p.message) for row in parsed.rows for p in row.errors
    ]
    return AppError(
        422,
        "import_invalid",
        f"The file has {len(problems)} problem(s) and nothing was imported. "
        "Preview it, fix the file and try again.",
        [ErrorDetail(field=f, message=m) for f, m in problems[:_MAX_ERROR_DETAILS]],
    )


def import_file(
    session: Session, ctx: TenantContext, filename: str, content: str
) -> tuple[ListingImport, list[tuple[ListingImportRow, str]]]:
    """All or nothing: any error refuses the whole file. Creates draft, private listings."""
    parsed = preview(session, ctx, content)
    if not parsed.ready:
        raise _invalid(parsed)
    batch = ListingImport(
        organisation_id=ctx.organisation_id,
        imported_by_user_id=ctx.user.id,
        filename=clean_filename(filename),
        row_count=len(parsed.rows),
    )
    session.add(batch)
    session.flush()
    created: list[tuple[ListingImportRow, str]] = []
    for row in parsed.rows:
        assert row.property and row.listing  # guaranteed by parsed.ready  # noqa: S101
        prop = listings.create_property(session, ctx, row.property)
        listing = listings.create_listing(
            session, ctx, row.listing.model_copy(update={"property_id": prop.id})
        )
        record = ListingImportRow(
            import_id=batch.id,
            organisation_id=ctx.organisation_id,
            row_number=row.number,
            external_id=row.external_id,
            listing_id=listing.id,
            property_id=prop.id,
            source=row.source,
        )
        session.add(record)
        created.append((record, listing.title))
    try:
        session.flush()
    except IntegrityError:
        # Another import of the same Listing ID committed after our preview check.
        raise AppError(
            409,
            "import_conflict",
            "Another import added one of these Listing IDs just now. Preview the file again.",
        ) from None
    session.refresh(batch)  # server-set created_at
    return batch, created


def get_source(
    session: Session, ctx: TenantContext, listing_id: UUID
) -> tuple[ListingImportRow, ListingImport] | None:
    listing = listings.get_listing(session, ctx, listing_id)  # 404 if not visible
    # Provenance is internal: another organisation seeing a shared listing does not get it.
    if listing.organisation_id != ctx.organisation_id:
        return None
    found = session.execute(
        select(ListingImportRow, ListingImport)
        .join(ListingImport, ListingImport.id == ListingImportRow.import_id)
        .where(ListingImportRow.listing_id == listing_id)
    ).first()
    return (found[0], found[1]) if found else None
