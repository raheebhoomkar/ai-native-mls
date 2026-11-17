from collections.abc import Sequence
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.core.pagination import Page, PageParamsDep
from app.modules.audit import service as audit
from app.modules.auth import service as auth
from app.modules.auth.deps import client_ip
from app.modules.compliance import service as compliance
from app.modules.listings import service
from app.modules.listings.models import Listing, Property
from app.modules.listings.schemas import (
    Address,
    AgentOut,
    Area,
    ListingCreate,
    ListingFeatureOut,
    ListingFilters,
    ListingOut,
    ListingUpdate,
    Money,
    PropertyCreate,
    PropertyOut,
    PropertyUpdate,
    StatusChangeOut,
    TransitionRequest,
)
from app.modules.organisations import service as organisations
from app.modules.organisations.deps import TenantContext, require

properties_router = APIRouter(prefix="/properties", tags=["properties"])
listings_router = APIRouter(prefix="/listings", tags=["listings"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]


def _property_out(prop: Property) -> PropertyOut:
    return PropertyOut(
        id=prop.id,
        organisation_id=prop.organisation_id,
        property_type=prop.property_type,
        address=Address(
            line1=prop.address_line1,
            line2=prop.address_line2,
            locality=prop.locality,
            city=prop.city,
            state=prop.state,
            postal_code=prop.postal_code,
            country=prop.country,
        ),
        bedrooms=prop.bedrooms,
        bathrooms=prop.bathrooms,
        area=(
            Area(value=prop.area_value, unit=prop.area_unit)
            if prop.area_value is not None and prop.area_unit is not None
            else None
        ),
        year_built=prop.year_built,
        version=prop.version,
        created_at=prop.created_at,
        updated_at=prop.updated_at,
        archived_at=prop.archived_at,
    )


def _listings_out(
    session: Session, ctx: TenantContext, listings: Sequence[Listing]
) -> list[ListingOut]:
    """Build responses for listings the caller may read, loading related rows in three queries."""
    properties = service.get_properties(session, [item.property_id for item in listings])
    agents = auth.get_users(session, [item.listing_agent_user_id for item in listings])
    names = organisations.get_names(session, [item.organisation_id for item in listings])
    return [
        ListingOut(
            id=item.id,
            organisation_id=item.organisation_id,
            organisation_name=names[item.organisation_id],
            status=item.status,
            listing_type=item.listing_type,
            visibility=item.visibility,
            title=item.title,
            remarks=item.remarks,
            list_price=Money(amount=item.list_price_amount, currency=item.list_price_currency),
            sold_price=(
                Money(amount=item.sold_price_amount, currency=item.list_price_currency)
                if item.sold_price_amount is not None
                else None
            ),
            expires_on=item.expires_on,
            listed_at=item.listed_at,
            closed_at=item.closed_at,
            listing_agent=AgentOut(
                user_id=item.listing_agent_user_id,
                full_name=agents[item.listing_agent_user_id].full_name,
            ),
            property=_property_out(properties[item.property_id]),
            allowed_transitions=service.allowed_transitions(ctx, item),
            can_edit=service.can_edit(ctx, item) and item.archived_at is None,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
            archived_at=item.archived_at,
        )
        for item in listings
    ]


def _audit(
    request: Request,
    session: Session,
    ctx: TenantContext,
    action: str,
    target_type: str,
    target_id: UUID,
    detail: dict[str, Any] | None = None,
) -> None:
    audit.record(
        session,
        action,
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type=target_type,
        target_id=str(target_id),
        ip_address=client_ip(request),
        detail=detail,
    )


# --- Properties ---------------------------------------------------------------------------


@properties_router.post("", status_code=201, responses=_ERRORS)
def create_property(
    body: PropertyCreate, request: Request, session: SessionDep, ctx: CanWrite
) -> PropertyOut:
    prop = service.create_property(session, ctx, body)
    _audit(request, session, ctx, "property.created", "property", prop.id)
    return _property_out(prop)


@properties_router.get("", responses=_ERRORS)
def list_properties(
    session: SessionDep,
    ctx: CanRead,
    page: PageParamsDep,
    q: Annotated[
        str | None, Query(max_length=100, description="Matches address, locality or city.")
    ] = None,
    include_archived: bool = False,
) -> Page[PropertyOut]:
    """Your organisation's properties, newest first."""
    items, next_cursor = service.list_properties(
        session, ctx, page, q=q, include_archived=include_archived
    )
    return Page(items=[_property_out(item) for item in items], next_cursor=next_cursor)


@properties_router.get("/{property_id}", responses=_ERRORS)
def get_property(property_id: UUID, session: SessionDep, ctx: CanRead) -> PropertyOut:
    return _property_out(service.get_property(session, ctx, property_id))


@properties_router.put("/{property_id}", responses=_ERRORS)
def update_property(
    property_id: UUID, body: PropertyUpdate, request: Request, session: SessionDep, ctx: CanWrite
) -> PropertyOut:
    prop = service.update_property(session, ctx, property_id, body)
    _audit(request, session, ctx, "property.updated", "property", prop.id)
    session.refresh(prop)
    return _property_out(prop)


@properties_router.delete("/{property_id}", status_code=204, responses=_ERRORS)
def archive_property(
    property_id: UUID, request: Request, session: SessionDep, ctx: CanWrite
) -> None:
    """Archive (soft delete). Refused while the property has listings that are not archived."""
    prop = service.archive_property(session, ctx, property_id)
    _audit(request, session, ctx, "property.archived", "property", prop.id)


# --- Listings -----------------------------------------------------------------------------


@listings_router.post("", status_code=201, responses=_ERRORS)
def create_listing(
    body: ListingCreate, request: Request, session: SessionDep, ctx: CanWrite
) -> ListingOut:
    """Create a draft listing for one of your organisation's properties."""
    listing = service.create_listing(session, ctx, body)
    _audit(request, session, ctx, "listing.created", "listing", listing.id)
    return _listings_out(session, ctx, [listing])[0]


@listings_router.get("", responses=_ERRORS)
def list_listings(
    session: SessionDep,
    ctx: CanRead,
    page: PageParamsDep,
    filters: Annotated[ListingFilters, Query()],
) -> Page[ListingOut]:
    """Listings you may see: your organisation's, plus those other organisations share.

    Do not change filters or sort while following `next_cursor`.
    """
    items, next_cursor = service.list_listings(session, ctx, filters, page)
    return Page(items=_listings_out(session, ctx, items), next_cursor=next_cursor)


@listings_router.get("/{listing_id}", responses=_ERRORS)
def get_listing(listing_id: UUID, session: SessionDep, ctx: CanRead) -> ListingOut:
    return _listings_out(session, ctx, [service.get_listing(session, ctx, listing_id)])[0]


@listings_router.patch("/{listing_id}", responses=_ERRORS)
def update_listing(
    listing_id: UUID, body: ListingUpdate, request: Request, session: SessionDep, ctx: CanWrite
) -> ListingOut:
    listing, changes = service.update_listing(session, ctx, listing_id, body)
    if changes:
        _audit(
            request,
            session,
            ctx,
            "listing.updated",
            "listing",
            listing.id,
            # Remarks can be long; the audit log records that they changed, not the text.
            {
                "changes": {
                    field: "changed" if field == "remarks" else [str(old), str(new)]
                    for field, (old, new) in changes.items()
                }
            },
        )
    session.refresh(listing)
    return _listings_out(session, ctx, [listing])[0]


@listings_router.post("/{listing_id}/transitions", responses=_ERRORS)
def transition_listing(
    listing_id: UUID, body: TransitionRequest, request: Request, session: SessionDep, ctx: CanWrite
) -> ListingOut:
    """Change a listing's status. `allowed_transitions` on the listing says what you may request."""
    if body.to == "active" and service.get_listing(session, ctx, listing_id).status == (
        "pending_review"
    ):
        compliance.ensure_approvable(session, listing_id)
    listing, previous = service.transition_listing(session, ctx, listing_id, body)
    _audit(
        request,
        session,
        ctx,
        "listing.status_changed",
        "listing",
        listing.id,
        {"from": previous, "to": listing.status},
    )
    # Submitting for review starts a policy check for the reviewer.
    if listing.status == "pending_review" and (
        run := compliance.scan_on_submit(session, ctx, listing.id)
    ):
        compliance.record_requested(session, ctx, run, client_ip(request))
    session.refresh(listing)
    return _listings_out(session, ctx, [listing])[0]


@listings_router.delete("/{listing_id}", status_code=204, responses=_ERRORS)
def archive_listing(listing_id: UUID, request: Request, session: SessionDep, ctx: CanWrite) -> None:
    """Archive (soft delete). Live listings must be withdrawn first."""
    listing = service.archive_listing(session, ctx, listing_id)
    _audit(request, session, ctx, "listing.archived", "listing", listing.id)


@listings_router.get("/{listing_id}/history", responses=_ERRORS)
def list_history(
    listing_id: UUID, session: SessionDep, ctx: CanRead, page: PageParamsDep
) -> Page[StatusChangeOut]:
    """Status changes, newest first. Only for the organisation that owns the listing."""
    items, next_cursor = service.list_history(session, ctx, listing_id, page)
    return Page(
        items=[StatusChangeOut.model_validate(item) for item in items], next_cursor=next_cursor
    )


@listings_router.get("/{listing_id}/features", responses=_ERRORS)
def list_features(listing_id: UUID, session: SessionDep, ctx: CanRead) -> list[ListingFeatureOut]:
    """Features a person confirmed, for example from reviewed AI suggestions."""
    listing = service.get_listing(session, ctx, listing_id)
    return [ListingFeatureOut.model_validate(f) for f in service.list_features(session, listing)]
