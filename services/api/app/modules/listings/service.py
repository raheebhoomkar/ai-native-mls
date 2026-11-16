from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError, ErrorDetail
from app.core.pagination import PageParams, paginate
from app.modules.listings.models import Listing, ListingStatusHistory, Property
from app.modules.listings.schemas import (
    ListingCreate,
    ListingFilters,
    ListingUpdate,
    PropertyCreate,
    PropertyUpdate,
    TransitionRequest,
)
from app.modules.organisations import service as organisations
from app.modules.organisations.deps import TenantContext

# --- Policy -------------------------------------------------------------------------------

# The whole status lifecycle. Anything not listed is rejected.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("pending_review", "withdrawn"),
    "pending_review": ("active", "draft", "withdrawn"),
    "active": ("temporarily_off_market", "sold", "withdrawn", "expired"),
    "temporarily_off_market": ("active", "withdrawn", "expired"),
    "withdrawn": ("draft",),
    "expired": ("draft",),
    "sold": (),
}

# A "network" listing is shown to other organisations only in these statuses;
# drafts, reviews, withdrawals and expiries stay inside the listing organisation.
NETWORK_STATUSES = ("active", "temporarily_off_market", "sold")


def _visible(ctx: TenantContext) -> ColumnElement[bool]:
    """The one rule for which listings a caller may read. Every read query uses it."""
    return or_(
        Listing.organisation_id == ctx.organisation_id,
        and_(
            Listing.visibility == "network",
            Listing.status.in_(NETWORK_STATUSES),
            Listing.archived_at.is_(None),
        ),
    )


def can_edit(ctx: TenantContext, listing: Listing) -> bool:
    if listing.organisation_id != ctx.organisation_id or not ctx.has("listing:write"):
        return False
    return ctx.has("listing:manage_all") or listing.listing_agent_user_id == ctx.user.id


def allowed_transitions(ctx: TenantContext, listing: Listing) -> list[str]:
    if listing.archived_at is not None or not can_edit(ctx, listing):
        return []
    return [
        target
        for target in TRANSITIONS[listing.status]
        # Approval is the one step that needs more than edit rights.
        if not (listing.status == "pending_review" and target == "active")
        or ctx.has("listing:publish")
    ]


def _not_found(what: str) -> AppError:
    return AppError(404, "not_found", f"{what} not found.")


def _forbidden() -> AppError:
    return AppError(403, "forbidden", "You do not have permission to do this.")


def _check_version(current: int, supplied: int) -> None:
    if current != supplied:
        raise _conflict()


def _conflict() -> AppError:
    return AppError(
        409, "version_conflict", "This record was changed by someone else. Reload and try again."
    )


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError:
        # Another request updated the row between our read and our write.
        raise _conflict() from None


# --- Properties ---------------------------------------------------------------------------


def _property_columns(data: PropertyCreate) -> dict[str, Any]:
    address = data.address
    return {
        "property_type": data.property_type,
        "address_line1": address.line1.strip(),
        "address_line2": address.line2,
        "locality": address.locality,
        "city": address.city.strip(),
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
        "bedrooms": data.bedrooms,
        "bathrooms": data.bathrooms,
        "area_value": data.area.value if data.area else None,
        "area_unit": data.area.unit if data.area else None,
        "year_built": data.year_built,
    }


def create_property(session: Session, ctx: TenantContext, data: PropertyCreate) -> Property:
    prop = Property(organisation_id=ctx.organisation_id, **_property_columns(data))
    session.add(prop)
    session.flush()
    session.refresh(prop)  # read back database-normalised values, e.g. 1250 -> 1250.00
    return prop


def get_property(session: Session, ctx: TenantContext, property_id: UUID) -> Property:
    prop = session.scalar(
        select(Property).where(
            Property.id == property_id, Property.organisation_id == ctx.organisation_id
        )
    )
    if prop is None:
        raise _not_found("Property")
    return prop


def get_properties(session: Session, property_ids: list[UUID]) -> dict[UUID, Property]:
    """For embedding in listings the caller is already allowed to read."""
    if not property_ids:
        return {}
    rows = session.scalars(select(Property).where(Property.id.in_(property_ids)))
    return {prop.id: prop for prop in rows}


def list_properties(
    session: Session, ctx: TenantContext, page: PageParams, *, q: str | None, include_archived: bool
) -> tuple[Sequence[Property], str | None]:
    stmt = select(Property).where(Property.organisation_id == ctx.organisation_id)
    if not include_archived:
        stmt = stmt.where(Property.archived_at.is_(None))
    if q:
        stmt = stmt.where(
            or_(
                Property.address_line1.icontains(q, autoescape=True),
                Property.locality.icontains(q, autoescape=True),
                Property.city.icontains(q, autoescape=True),
            )
        )
    return paginate(session, stmt, page, sort=Property.created_at, id_column=Property.id)


def update_property(
    session: Session, ctx: TenantContext, property_id: UUID, data: PropertyUpdate
) -> Property:
    prop = get_property(session, ctx, property_id)
    _check_version(prop.version, data.version)
    for column, value in _property_columns(data).items():
        setattr(prop, column, value)
    _flush(session)
    return prop


def archive_property(session: Session, ctx: TenantContext, property_id: UUID) -> Property:
    prop = get_property(session, ctx, property_id)
    in_use = session.scalar(
        select(exists().where(Listing.property_id == prop.id, Listing.archived_at.is_(None)))
    )
    if in_use:
        raise AppError(
            409, "property_in_use", "Archive this property's listings before archiving it."
        )
    if prop.archived_at is None:
        prop.archived_at = datetime.now(UTC)
        _flush(session)
    return prop


# --- Listings -----------------------------------------------------------------------------


def _check_agent(session: Session, ctx: TenantContext, agent_user_id: UUID) -> None:
    if agent_user_id != ctx.user.id and not ctx.has("listing:manage_all"):
        raise _forbidden()
    if organisations.get_membership(session, ctx.organisation_id, agent_user_id) is None:
        raise AppError(
            422,
            "validation_error",
            "Request validation failed.",
            [
                ErrorDetail(
                    field="body.listing_agent_user_id",
                    message="The listing agent must be a member of this organisation.",
                )
            ],
        )


def _record_status(
    session: Session, ctx: TenantContext, listing: Listing, previous: str | None, reason: str | None
) -> None:
    session.add(
        ListingStatusHistory(
            listing_id=listing.id,
            organisation_id=listing.organisation_id,
            from_status=previous,
            to_status=listing.status,
            changed_by_user_id=ctx.user.id,
            reason=reason,
            # Set here, not by the database: now() is the transaction's start time, which
            # would give equal timestamps to changes made in one transaction.
            changed_at=datetime.now(UTC),
        )
    )


def create_listing(session: Session, ctx: TenantContext, data: ListingCreate) -> Listing:
    prop = get_property(session, ctx, data.property_id)  # 404 for another tenant's property
    if prop.archived_at is not None:
        raise AppError(409, "property_archived", "This property is archived.")
    agent_user_id = data.listing_agent_user_id or ctx.user.id
    _check_agent(session, ctx, agent_user_id)
    listing = Listing(
        organisation_id=ctx.organisation_id,
        property_id=prop.id,
        listing_agent_user_id=agent_user_id,
        status="draft",
        listing_type=data.listing_type,
        visibility=data.visibility,
        title=data.title.strip(),
        remarks=data.remarks,
        list_price_amount=data.list_price.amount,
        list_price_currency=data.list_price.currency,
        expires_on=data.expires_on,
    )
    session.add(listing)
    session.flush()
    _record_status(session, ctx, listing, None, None)
    session.flush()
    session.refresh(listing)  # read back database-normalised values, e.g. 100 -> 100.00
    return listing


def get_listing(session: Session, ctx: TenantContext, listing_id: UUID) -> Listing:
    listing = session.scalar(select(Listing).where(Listing.id == listing_id, _visible(ctx)))
    if listing is None:
        raise _not_found("Listing")
    return listing


def _get_editable(session: Session, ctx: TenantContext, listing_id: UUID, version: int) -> Listing:
    listing = get_listing(session, ctx, listing_id)  # 404 if the caller cannot even see it
    if not can_edit(ctx, listing):
        raise _forbidden()
    if listing.archived_at is not None:
        raise AppError(409, "listing_archived", "This listing is archived.")
    _check_version(listing.version, version)
    return listing


def list_listings(
    session: Session, ctx: TenantContext, filters: ListingFilters, page: PageParams
) -> tuple[Sequence[Listing], str | None]:
    stmt = select(Listing).join(Property, Property.id == Listing.property_id).where(_visible(ctx))
    if filters.scope == "organisation":
        stmt = stmt.where(Listing.organisation_id == ctx.organisation_id)
    elif filters.scope == "network":
        stmt = stmt.where(Listing.organisation_id != ctx.organisation_id)
    if not filters.include_archived:
        stmt = stmt.where(Listing.archived_at.is_(None))
    if filters.status:
        stmt = stmt.where(Listing.status.in_(filters.status))
    if filters.listing_type:
        stmt = stmt.where(Listing.listing_type == filters.listing_type)
    if filters.property_type:
        stmt = stmt.where(Property.property_type == filters.property_type)
    if filters.city:
        stmt = stmt.where(Property.city.ilike(filters.city.strip(), escape="\\"))
    if filters.locality:
        stmt = stmt.where(Property.locality.ilike(filters.locality.strip(), escape="\\"))
    if filters.min_price is not None:
        stmt = stmt.where(Listing.list_price_amount >= filters.min_price)
    if filters.max_price is not None:
        stmt = stmt.where(Listing.list_price_amount <= filters.max_price)
    if filters.min_bedrooms is not None:
        stmt = stmt.where(Property.bedrooms >= filters.min_bedrooms)
    if filters.listing_agent_user_id:
        stmt = stmt.where(Listing.listing_agent_user_id == filters.listing_agent_user_id)
    if filters.q:
        stmt = stmt.where(
            or_(
                Listing.title.icontains(filters.q, autoescape=True),
                Property.locality.icontains(filters.q, autoescape=True),
                Property.city.icontains(filters.q, autoescape=True),
            )
        )
    by_price = filters.sort.startswith("price")
    return paginate(
        session,
        stmt,
        page,
        sort=Listing.list_price_amount if by_price else Listing.created_at,
        id_column=Listing.id,
        descending=filters.sort in ("newest", "price_desc"),
    )


def update_listing(
    session: Session, ctx: TenantContext, listing_id: UUID, data: ListingUpdate
) -> tuple[Listing, dict[str, Any]]:
    """Apply the sent fields. Returns the listing and `{field: [old, new]}` for the audit log."""
    listing = _get_editable(session, ctx, listing_id, data.version)
    if listing.status == "sold":
        raise AppError(409, "listing_closed", "A sold listing cannot be edited.")
    sent = data.model_fields_set - {"version"}
    updates: dict[str, Any] = {}
    for field in sent & {"listing_type", "title", "remarks", "visibility", "expires_on"}:
        updates[field] = getattr(data, field)
    if "title" in updates:
        updates["title"] = updates["title"].strip()
    if data.list_price is not None:
        updates["list_price_amount"] = data.list_price.amount
        updates["list_price_currency"] = data.list_price.currency
    if data.listing_agent_user_id is not None:
        _check_agent(session, ctx, data.listing_agent_user_id)
        updates["listing_agent_user_id"] = data.listing_agent_user_id

    changes: dict[str, Any] = {}
    for column, value in updates.items():
        old = getattr(listing, column)
        if old != value:
            changes[column] = [old, value]
            setattr(listing, column, value)
    _flush(session)
    return listing, changes


def transition_listing(
    session: Session, ctx: TenantContext, listing_id: UUID, data: TransitionRequest
) -> tuple[Listing, str]:
    """Change status. Every status change in the system goes through here.

    Returns the listing and its previous status.
    """
    listing = _get_editable(session, ctx, listing_id, data.version)
    previous = listing.status
    if data.to not in TRANSITIONS[previous]:
        allowed = ", ".join(TRANSITIONS[previous]) or "none"
        raise AppError(
            409,
            "invalid_transition",
            f"A listing that is {previous} cannot become {data.to}. Allowed: {allowed}.",
        )
    if data.to not in allowed_transitions(ctx, listing):
        raise _forbidden()

    now = datetime.now(UTC)
    listing.status = data.to
    if data.to == "active" and listing.listed_at is None:
        listing.listed_at = now
    if data.to == "sold" and data.sold_price is not None:
        if data.sold_price.currency != listing.list_price_currency:
            raise AppError(
                422,
                "validation_error",
                "Request validation failed.",
                [
                    ErrorDetail(
                        field="body.sold_price.currency",
                        message=f"Must match the list price currency "
                        f"({listing.list_price_currency}).",
                    )
                ],
            )
        listing.sold_price_amount = data.sold_price.amount
        listing.closed_at = now
    _flush(session)
    _record_status(session, ctx, listing, previous, data.reason)
    session.flush()
    return listing, previous


def archive_listing(session: Session, ctx: TenantContext, listing_id: UUID) -> Listing:
    listing = get_listing(session, ctx, listing_id)
    if not can_edit(ctx, listing):
        raise _forbidden()
    if listing.status in ("active", "pending_review", "temporarily_off_market"):
        raise AppError(
            409,
            "listing_live",
            f"A listing that is {listing.status} cannot be archived. Withdraw it first.",
        )
    if listing.archived_at is None:
        listing.archived_at = datetime.now(UTC)
        _flush(session)
    return listing


def list_history(
    session: Session, ctx: TenantContext, listing_id: UUID, page: PageParams
) -> tuple[Sequence[ListingStatusHistory], str | None]:
    listing = get_listing(session, ctx, listing_id)
    if listing.organisation_id != ctx.organisation_id:
        # Other organisations may see a shared listing, but not its internal history.
        raise _forbidden()
    stmt = select(ListingStatusHistory).where(ListingStatusHistory.listing_id == listing.id)
    return paginate(
        session,
        stmt,
        page,
        sort=ListingStatusHistory.changed_at,
        id_column=ListingStatusHistory.id,
    )
