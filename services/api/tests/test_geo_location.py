"""Property locations (Module 7): geocoding job, manual points, permissions."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ai.providers import ProviderRejected, ProviderUnavailable
from app.modules.audit.models import AuditEvent
from app.modules.geo import service as geo
from app.modules.geo.geocoder import GeocodeQuery, GeocodeResult
from app.modules.jobs.models import Job
from tests.test_ai_extraction import skip_backoff
from tests.test_listings import PROPERTIES, brokerage, property_body
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here


def create(client: TestClient, **address: Any) -> dict[str, Any]:
    body = property_body()
    body["address"].update(address)
    response = client.post(PROPERTIES, json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def fetch(client: TestClient, prop: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"{PROPERTIES}/{prop['id']}").json()
    return result


def put(client: TestClient, prop: dict[str, Any], **address: Any) -> dict[str, Any]:
    body = {**{k: prop[k] for k in ("property_type", "address", "bedrooms", "bathrooms")}}
    body["address"] = {**prop["address"], **address}
    body["version"] = prop["version"]
    response = client.put(f"{PROPERTIES}/{prop['id']}", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def geo_jobs(db: Session) -> int:
    return db.scalar(select(func.count()).where(Job.kind == "geo.geocode")) or 0


def test_new_property_is_located_by_the_demo_geocoder(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    prop = create(clients["agent"])
    assert (prop["location_status"], prop["location"]) == ("pending", None)

    run_jobs(db)
    located = fetch(clients["agent"], prop)
    assert located["location_status"] == "located"
    location = located["location"]
    assert (location["source"], location["precision"]) == ("demo", "locality")  # Powai
    assert (location["latitude"], location["longitude"]) == ("19.1176000", "72.9060000")
    assert location["attribution"] is None
    # Locating does not change the version, so an edit started before it still saves.
    assert located["version"] == prop["version"]
    put(clients["agent"], prop, line2="Tower B")
    events = db.scalars(select(AuditEvent.action).where(AuditEvent.target_id == prop["id"]))
    assert "property.geocoded" in list(events)


def test_address_change_locates_again_other_edits_do_not(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    prop = create(clients["agent"])
    run_jobs(db)
    prop = put(clients["agent"], fetch(clients["agent"], prop), line2="Tower B")
    assert prop["location_status"] == "located"
    assert geo_jobs(db) == 1

    prop = put(clients["agent"], prop, city="Pune")
    assert (prop["location_status"], prop["location"]) == ("pending", None)
    run_jobs(db)
    assert fetch(clients["agent"], prop)["location"]["latitude"] == "18.5204000"


def test_unknown_address_is_not_found(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    prop = create(clients["agent"], city="Atlantis")
    run_jobs(db)
    prop = fetch(clients["agent"], prop)
    assert (prop["location_status"], prop["location"]) == ("not_found", None)
    assert "Set the point by hand" in prop["location_error"]


class Failing:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def geocode(self, query: GeocodeQuery) -> GeocodeResult | None:
        raise self.error


def test_refused_lookup_fails_at_once(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    monkeypatch.setattr(geo, "get_geocoder", lambda: Failing(ProviderRejected("blocked (403)")))
    prop = create(clients["agent"])
    run_jobs(db)
    prop = fetch(clients["agent"], prop)
    assert (prop["location_status"], prop["location_error"]) == ("failed", "blocked (403)")


def test_outage_retries_then_fails(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    monkeypatch.setattr(geo, "get_geocoder", lambda: Failing(ProviderUnavailable("down")))
    prop = create(clients["agent"])
    for _ in range(3):
        run_jobs(db)
        skip_backoff(db)
    prop = fetch(clients["agent"], prop)
    assert prop["location_status"] == "failed"
    assert prop["location_error"].startswith("The address could not be located")


def test_point_set_by_hand_wins_and_survives_address_changes(
    db: Session, brokerage: Brokerage
) -> None:
    _, _, clients = brokerage
    prop = create(clients["agent"])
    point = {"latitude": "19.1180000", "longitude": "72.9060000"}
    response = clients["agent"].put(f"{PROPERTIES}/{prop['id']}/location", json=point)
    assert response.status_code == 200, response.text
    location = response.json()["location"]
    assert (location["source"], location["latitude"]) == ("manual", "19.1180000")

    run_jobs(db)  # the queued lookup finds the point already set and leaves it
    prop = put(clients["agent"], fetch(clients["agent"], prop), city="Pune")
    assert prop["location"]["source"] == "manual"
    assert geo_jobs(db) == 1
    events = db.scalars(select(AuditEvent.action).where(AuditEvent.target_id == prop["id"]))
    assert "property.location_set" in list(events)


def test_location_input_and_access_are_checked(
    brokerage: Brokerage, make_user: Any, make_org: Any, login_as: Any
) -> None:
    _, _, clients = brokerage
    prop = create(clients["agent"])
    url = f"{PROPERTIES}/{prop['id']}/location"
    bad = clients["agent"].put(url, json={"latitude": "95", "longitude": "0"})
    assert bad.status_code == 422
    point = {"latitude": "19", "longitude": "72"}
    assert clients["api"].put(url, json=point).status_code == 403
    outsider = make_user("agent@b.example")
    make_org("Brokerage B", {outsider: "agent"})
    assert login_as(outsider).put(url, json=point).status_code == 404


def test_enrichment_says_not_available_with_a_reason(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    prop = create(clients["agent"])
    url = f"{PROPERTIES}/{prop['id']}/enrichment"
    items = clients["agent"].get(url).json()
    assert {item["reason"] for item in items} == {"This property has no location yet."}

    run_jobs(db)
    items = clients["agent"].get(url).json()
    assert [item["key"] for item in items] == [
        "nearest_metro_station",
        "schools_within_2km",
        "flood_risk",
    ]
    assert all(item["value"] is None and item["source"] is None for item in items)
    assert {item["reason"] for item in items} == {"No neighbourhood data source is set up."}
