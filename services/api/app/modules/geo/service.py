"""Locating properties: the geocoding job and setting a point by hand.

Location columns are written with UPDATE statements, never through the ORM object, so the
property's `version` does not change and an agent editing the property gets no false 409.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.ai.providers import ProviderError
from app.modules.audit import service as audit
from app.modules.geo.geocoder import GeocodeQuery, get_geocoder
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings.models import Property

_CLEARED: dict[str, Any] = {
    "latitude": None,
    "longitude": None,
    "geo_source": None,
    "geo_precision": None,
    "located_at": None,
    "geo_error": None,
}


def _set(session: Session, property_id: UUID, **values: Any) -> None:
    session.execute(
        update(Property)
        .where(Property.id == property_id)
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )


def request_geocode(session: Session, prop: Property) -> None:
    """Forget the old point and queue a lookup. A point set by hand is kept."""
    if prop.geo_source == "manual":
        return
    _set(session, prop.id, geo_status="pending", **_CLEARED)
    jobs.enqueue(
        session, "geo.geocode", {"property_id": str(prop.id)}, organisation_id=prop.organisation_id
    )


def set_location(session: Session, prop: Property, latitude: Decimal, longitude: Decimal) -> None:
    _set(
        session,
        prop.id,
        latitude=latitude,
        longitude=longitude,
        geo_status="located",
        geo_source="manual",
        geo_precision="address",
        located_at=datetime.now(UTC),
        geo_error=None,
    )


def _failed(session: Session, job: Job) -> None:
    _set(
        session,
        UUID(job.payload["property_id"]),
        geo_status="failed",
        **{**_CLEARED, "geo_error": "The address could not be located. Set the point by hand."},
    )


@jobs.handler("geo.geocode", on_failed=_failed)
def geocode(session: Session, job: Job) -> None:
    """Idempotent: does nothing unless the property is still waiting for a lookup."""
    prop = session.get(Property, UUID(job.payload["property_id"]))
    if prop is None or prop.geo_status != "pending":
        return
    query = GeocodeQuery(
        address_line1=prop.address_line1,
        locality=prop.locality,
        city=prop.city,
        state=prop.state,
        postal_code=prop.postal_code,
        country=prop.country,
    )
    refused: str | None = None
    try:
        result = get_geocoder().geocode(query)
    except ProviderError as error:
        if error.retryable:
            raise
        result, refused = None, str(error)

    if result is not None:
        values: dict[str, Any] = {
            "geo_status": "located",
            "latitude": result.latitude,
            "longitude": result.longitude,
            "geo_source": result.source,
            "geo_precision": result.precision,
            "located_at": result.retrieved_at,
            "geo_error": None,
        }
    else:
        values = {
            **_CLEARED,
            "geo_status": "failed" if refused else "not_found",
            "geo_error": (refused or "No match for this address. Set the point by hand.")[:300],
        }
    _set(session, prop.id, **values)
    audit.record(
        session,
        "property.geocoded",
        organisation_id=prop.organisation_id,
        target_type="property",
        target_id=str(prop.id),
        detail={
            "status": values["geo_status"],
            "source": values.get("geo_source"),
            "precision": values.get("geo_precision"),
        },
    )
