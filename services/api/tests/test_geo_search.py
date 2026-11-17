"""Radius and bounding-box search over listings (Module 7)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.geo.distance import haversine_km
from tests.test_listings import LISTINGS, brokerage, new_listing, property_body
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here

MUMBAI = {"near_lat": 19.076, "near_lon": 72.8777}


def in_city(client: TestClient, city: str) -> dict[str, Any]:
    body = property_body()
    body["address"].update(city=city, locality=None)  # city centres, for known distances
    return new_listing(client, property=body, title=f"Flat in {city}")


def titles(client: TestClient, **params: Any) -> dict[str, float | None]:
    response = client.get(LISTINGS, params=params)
    assert response.status_code == 200, response.text
    return {item["title"]: item["distance_km"] for item in response.json()["items"]}


@pytest.fixture
def cities(db: Session, brokerage: Brokerage) -> TestClient:
    _, _, clients = brokerage
    for city in ("Mumbai", "Thane", "Pune", "Atlantis"):
        in_city(clients["agent"], city)
    run_jobs(db)
    return clients["agent"]


def test_radius_search_returns_listings_within_the_radius_with_distance(
    cities: TestClient,
) -> None:
    found = titles(cities, **MUMBAI, radius_km=25)
    assert set(found) == {"Flat in Mumbai", "Flat in Thane"}
    assert found["Flat in Mumbai"] == 0.0
    assert found["Flat in Thane"] == pytest.approx(19.3, abs=0.5)
    assert set(titles(cities, **MUMBAI, radius_km=0.1)) == {"Flat in Mumbai"}
    # Without a radius search there is no distance.
    assert set(titles(cities).values()) == {None}


def test_bounding_box_search(cities: TestClient) -> None:
    box = {"min_lat": 18, "max_lat": 19, "min_lon": 73.5, "max_lon": 74.2}
    assert set(titles(cities, **box)) == {"Flat in Pune"}


def test_other_organisations_private_listings_stay_hidden(
    db: Session, cities: TestClient, make_user: Any, make_org: Any, login_as: Any
) -> None:
    outsider = make_user("agent@b.example")
    make_org("Brokerage B", {outsider: "agent"})
    in_city(login_as(outsider), "Mumbai")
    run_jobs(db)
    assert set(titles(cities, **MUMBAI, radius_km=5)) == {"Flat in Mumbai"}
    assert len(titles(login_as(outsider), **MUMBAI, radius_km=5)) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"near_lat": 19, "near_lon": 72},
        {**MUMBAI, "radius_km": 101},
        {**MUMBAI, "radius_km": 0},
        {"near_lat": 91, "near_lon": 72, "radius_km": 5},
        {"min_lat": 18, "max_lat": 19, "min_lon": 73},
        {"min_lat": 19, "max_lat": 18, "min_lon": 73, "max_lon": 74},
    ],
)
def test_invalid_geo_filters_are_rejected(brokerage: Brokerage, params: dict[str, Any]) -> None:
    _, _, clients = brokerage
    assert clients["agent"].get(LISTINGS, params=params).status_code == 422


def test_python_distance_matches_known_value() -> None:
    # Mumbai to Pune centres: about 120 km in a straight line.
    assert haversine_km(19.076, 72.8777, 18.5204, 73.8567) == pytest.approx(119.9, abs=1)
