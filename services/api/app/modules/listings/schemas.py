from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PropertyType = Literal["apartment", "house", "villa", "plot", "commercial", "other"]
AreaUnit = Literal["sqft", "sqm"]
ListingType = Literal["sale", "rent"]
Status = Literal[
    "draft",
    "pending_review",
    "active",
    "temporarily_off_market",
    "sold",
    "withdrawn",
    "expired",
]
Visibility = Literal["private", "network"]

# Decimal in, string out: JSON numbers would lose precision in some clients.
Amount = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code")]
Text200 = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Rooms = Annotated[int, Field(ge=0, le=100)]
Version = Annotated[
    int, Field(ge=1, description="The version you last read. A mismatch returns 409.")
]


class Money(BaseModel):
    amount: Amount
    currency: Currency


class Area(BaseModel):
    value: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    unit: AreaUnit


class Address(BaseModel):
    line1: Text200
    line2: Annotated[str, Field(max_length=200)] | None = None
    locality: Annotated[str, Field(max_length=100)] | None = None
    city: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    state: Annotated[str, Field(max_length=100)] | None = None
    postal_code: Annotated[str, Field(max_length=20)] | None = None
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2")]


class PropertyCreate(BaseModel):
    property_type: PropertyType
    address: Address
    bedrooms: Rooms | None = None
    bathrooms: Rooms | None = None
    area: Area | None = None
    year_built: Annotated[int, Field(ge=1600, le=2100)] | None = None


class PropertyUpdate(PropertyCreate):
    """Replaces the property's details. Send every field, as returned by GET."""

    version: Version


Latitude = Annotated[Decimal, Field(ge=-90, le=90, max_digits=9, decimal_places=7)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180, max_digits=10, decimal_places=7)]


class LocationIn(BaseModel):
    """A point set by hand. Kept when the address changes; set it again to correct it."""

    latitude: Latitude
    longitude: Longitude


class Location(LocationIn):
    source: Literal["demo", "nominatim", "manual"]
    precision: Literal["address", "locality", "city"] = Field(
        description="How close the point is to the property: the building, the area or the city."
    )
    located_at: datetime
    attribution: str | None = Field(description="Credit the data source requires, if any.")


class EnrichmentItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    value: str | None
    source: str | None
    retrieved_at: datetime | None
    reason: str | None = Field(description="Why there is no value. Set exactly when value is null.")


class PropertyOut(PropertyCreate):
    id: UUID
    organisation_id: UUID
    location: Location | None
    location_status: Literal["pending", "located", "not_found", "failed"] | None = Field(
        description="None for properties created before locations existed."
    )
    location_error: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ListingCreate(BaseModel):
    property_id: UUID
    listing_type: ListingType
    title: Text200
    remarks: Annotated[str, Field(max_length=10_000)] | None = None
    list_price: Money
    visibility: Visibility = "private"
    expires_on: date | None = None
    # Defaults to you. Assigning someone else needs listing:manage_all.
    listing_agent_user_id: UUID | None = None


class ListingUpdate(BaseModel):
    """Send only the fields to change, plus `version`. Status changes use /transitions."""

    version: Version
    listing_type: ListingType | None = None
    title: Text200 | None = None
    remarks: Annotated[str, Field(max_length=10_000)] | None = None
    list_price: Money | None = None
    visibility: Visibility | None = None
    expires_on: date | None = None
    listing_agent_user_id: UUID | None = None

    @model_validator(mode="after")
    def _required_fields_cannot_be_cleared(self) -> Self:
        for field in ("listing_type", "title", "list_price", "visibility", "listing_agent_user_id"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TransitionRequest(BaseModel):
    to: Status
    version: Version
    reason: Annotated[str, Field(max_length=2000)] | None = None
    sold_price: Money | None = None

    @model_validator(mode="after")
    def _sold_price_only_when_sold(self) -> Self:
        if (self.to == "sold") != (self.sold_price is not None):
            raise ValueError("sold_price is required when marking sold, and only then")
        return self


class AgentOut(BaseModel):
    user_id: UUID
    full_name: str


class ListingOut(BaseModel):
    id: UUID
    organisation_id: UUID
    organisation_name: str
    status: Status
    listing_type: ListingType
    visibility: Visibility
    title: str
    remarks: str | None
    list_price: Money
    # As reported by the listing agent. Not a verified transaction price.
    sold_price: Money | None
    expires_on: date | None
    listed_at: datetime | None
    closed_at: datetime | None
    listing_agent: AgentOut
    property: PropertyOut
    # Status changes you may request now, given your role.
    allowed_transitions: list[Status]
    can_edit: bool
    distance_km: float | None = Field(
        default=None, description="From near_lat, near_lon, in km to 2 decimals; only then."
    )
    cover_url: str | None = Field(
        default=None,
        description="Signed, short-lived thumbnail of the first photo; null when none is ready.",
    )
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class StatusChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    from_status: Status | None
    to_status: Status
    changed_by_user_id: UUID
    reason: str | None
    changed_at: datetime


class ListingFeatureOut(BaseModel):
    """A person-confirmed observable feature. `media_asset_id` is the photo that shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attribute: str
    value: str
    source: str
    media_asset_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime


class ListingFilters(BaseModel):
    scope: Literal["all", "organisation", "network"] = Field(
        default="all",
        description="organisation: your organisation's listings. "
        "network: listings other organisations share. all: both.",
    )
    status: list[Status] = Field(default_factory=list)
    listing_type: ListingType | None = None
    property_type: PropertyType | None = None
    city: Annotated[str, Field(max_length=100)] | None = None
    locality: Annotated[str, Field(max_length=100)] | None = None
    min_price: Annotated[Decimal, Field(ge=0)] | None = None
    max_price: Annotated[Decimal, Field(ge=0)] | None = None
    min_bedrooms: Rooms | None = None
    listing_agent_user_id: UUID | None = None
    q: (
        Annotated[str, Field(max_length=100, description="Matches title, locality or city.")] | None
    ) = None
    include_archived: bool = False
    sort: Literal["newest", "oldest", "price_asc", "price_desc"] = "newest"
    # Search filters, not stored values: plain floats, any number of decimals.
    near_lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    near_lon: Annotated[float, Field(ge=-180, le=180)] | None = None
    radius_km: (
        Annotated[float, Field(ge=0.1, le=100, description="With near_lat, near_lon.")] | None
    ) = None
    min_lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    min_lon: Annotated[float, Field(ge=-180, le=180)] | None = None
    max_lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    max_lon: Annotated[float, Field(ge=-180, le=180)] | None = None

    @model_validator(mode="after")
    def _geo_filters_complete(self) -> Self:
        near = (self.near_lat, self.near_lon, self.radius_km)
        if any(v is not None for v in near) and None in near:
            raise ValueError("near_lat, near_lon and radius_km go together")
        box = (self.min_lat, self.min_lon, self.max_lat, self.max_lon)
        if any(v is not None for v in box):
            if None in box:
                raise ValueError("min_lat, min_lon, max_lat and max_lon go together")
            if self.min_lat > self.max_lat or self.min_lon > self.max_lon:  # type: ignore[operator]
                raise ValueError("min_lat and min_lon must not be above max_lat and max_lon")
        return self
