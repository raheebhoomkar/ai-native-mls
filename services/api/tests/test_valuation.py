"""Valuation and simulation (Module 9)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.listings.models import Listing
from app.modules.valuation.service import simulate_days_on_market
from tests.test_listings import LISTINGS, brokerage, move, new_listing, property_body, publish
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here


def sold(
    db: Session,
    agent: TestClient,
    broker: TestClient,
    price: int,
    *,
    title: str = "Comp",
    closed_days_ago: int = 30,
    dom: int = 40,
    **overrides: Any,
) -> dict[str, Any]:
    overrides.setdefault("property", property_body(area={"value": "1000", "unit": "sqft"}))
    listing = publish(agent, broker, title=title, **overrides)
    listing = move(agent, listing, "sold", sold_price={"amount": str(price), "currency": "INR"})
    closed = datetime.now(UTC) - timedelta(days=closed_days_ago)
    db.execute(
        update(Listing)
        .where(Listing.id == UUID(listing["id"]))
        .values(closed_at=closed, listed_at=closed - timedelta(days=dom))
    )
    db.commit()
    return listing


def value(client: TestClient, listing: dict[str, Any], **body: Any) -> dict[str, Any]:
    response = client.post(f"{LISTINGS}/{listing['id']}/valuations", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def six_comps(db: Session, clients: dict[str, TestClient]) -> None:
    for i, dom in enumerate((20, 30, 40, 50, 60, 70)):
        sold(db, clients["agent"], clients["broker"], 10_000_000 + i * 1_000_000, dom=dom)


def test_estimate_from_comparable_sales_with_assumptions(db: Session, brokerage: Brokerage) -> None:
    clients = brokerage[2]
    six_comps(db, clients)
    # Not comparable: a villa, a rental, too large, closed too long ago.
    sold(
        db,
        clients["agent"],
        clients["broker"],
        99_000_000,
        title="Villa",
        property=property_body(property_type="villa", area={"value": "1000", "unit": "sqft"}),
    )
    sold(db, clients["agent"], clients["broker"], 90_000, title="Rental", listing_type="rent")
    sold(
        db,
        clients["agent"],
        clients["broker"],
        99_000_000,
        title="Big",
        property=property_body(area={"value": "5000", "unit": "sqft"}),
    )
    sold(db, clients["agent"], clients["broker"], 1_000_000, title="Old", closed_days_ago=800)
    # Asking prices are reported apart and never used.
    publish(
        clients["agent"],
        clients["broker"],
        title="Asking",
        property=property_body(area={"value": "1000", "unit": "sqft"}),
        list_price={"amount": "50000000", "currency": "INR"},
    )
    subject = new_listing(clients["agent"])  # 1250.50 sqft in Powai
    run_jobs(db)  # locate everything, so distance is used

    valuation = value(clients["agent"], subject, seed=7)

    assert valuation["status"] == "ok"
    assert "Not an appraisal" in valuation["disclaimer"]
    assert (valuation["model_version"], valuation["simulation_version"]) == (
        "baseline-ppsf-v1",
        "dom-lognormal-v1",
    )
    result = valuation["result"]
    assert result["sample_size"] == 6
    assert {comp["title"] for comp in result["comps"]} == {"Comp"}
    assert all("not verified" in comp["price_source"] for comp in result["comps"])
    assert result["comps"][0]["distance_km"] == 0.0
    # Price per sqft 10000..15000: quartiles 11250, 12500, 13750, times 1250.50 sqft.
    estimate = result["estimate"]
    assert estimate["method"] == "price_per_sqft"
    assert estimate["median"] == {"amount": "15631250.00", "currency": "INR"}
    assert estimate["low"]["amount"] == "14068125.00"
    assert estimate["high"]["amount"] == "17194375.00"
    assert result["asking"]["count"] == 1
    assert result["asking"]["median"] == "50000"
    assert any("Condition is not recorded" in line for line in result["assumptions"])
    assert "Offers are not recorded" in result["offers_reason"]
    simulation = result["simulation"]
    assert simulation["available"] is True
    assert (simulation["seed"], simulation["samples"], simulation["runs"]) == (7, 6, 2000)
    assert 20 <= simulation["days_p50"] <= 70
    assert simulation["days_p10"] <= simulation["days_p50"] <= simulation["days_p90"]

    # The same seed and data give the same answer; the stored parameters say so.
    again = value(clients["agent"], subject, seed=7)
    assert again["result"]["simulation"] == simulation
    assert again["parameters"]["seed"] == 7
    stored = clients["agent"].get(f"{LISTINGS}/{subject['id']}/valuations").json()
    assert [item["id"] for item in stored] == [again["id"], valuation["id"]]


def test_too_few_comps_is_insufficient_data_with_no_number(
    db: Session, brokerage: Brokerage
) -> None:
    clients = brokerage[2]
    sold(db, clients["agent"], clients["broker"], 10_000_000)
    subject = new_listing(clients["agent"])

    result = value(clients["agent"], subject)
    assert result["status"] == "insufficient_data"
    assert result["result"]["estimate"] is None
    assert "Insufficient data: 1 comparable sale found" in result["result"]["reason"]
    assert result["result"]["simulation"]["available"] is False
    assert isinstance(result["parameters"]["seed"], int)  # chosen and stored


def test_only_the_owning_organisation_values_and_sees_other_private_sales_never(
    db: Session, brokerage: Brokerage, make_user: Any, make_org: Any, login_as: Any
) -> None:
    clients = brokerage[2]
    agent_b, broker_b = make_user("agent@b.example"), make_user("broker@b.example")
    make_org("Brokerage B", {agent_b: "agent", broker_b: "broker"})
    other, other_broker = login_as(agent_b), login_as(broker_b)
    for i in range(3):
        sold(db, other, other_broker, 20_000_000 + i, title="B private")
    sold(db, other, other_broker, 12_000_000, title="B shared", visibility="network")
    subject = publish(clients["agent"], clients["broker"], visibility="network")

    comps = value(clients["agent"], subject)["result"]["comps"]
    assert [(comp["title"], comp["organisation_name"]) for comp in comps] == [
        ("B shared", "Brokerage B")
    ]
    # Brokerage B can see the shared listing but cannot value it.
    response = other.post(f"{LISTINGS}/{subject['id']}/valuations", json={})
    assert response.status_code == 404
    assert other.get(f"{LISTINGS}/{subject['id']}/valuations").status_code == 404


def test_later_sale_is_recorded_as_the_outcome_and_evaluated(
    db: Session, brokerage: Brokerage
) -> None:
    clients = brokerage[2]
    six_comps(db, clients)
    subject = publish(clients["agent"], clients["broker"])
    valuation = value(clients["agent"], subject, seed=1)
    assert valuation["outcome"] is None

    move(clients["agent"], subject, "sold", sold_price={"amount": "15000000", "currency": "INR"})
    run_jobs(db)
    stored = clients["agent"].get(f"{LISTINGS}/{subject['id']}/valuations").json()[0]
    outcome = stored["outcome"]
    assert outcome["price"] == {"amount": "15000000.00", "currency": "INR"}
    assert outcome["error_pct"] == round((15631250 - 15000000) / 15000000, 4)
    assert outcome["within_range"] is True
    metrics = clients["agent"].get("/api/v1/valuations/evaluation").json()
    assert metrics == [
        {
            "model_version": "baseline-ppsf-v1",
            "count": 1,
            "median_abs_error_pct": outcome["error_pct"],
            "within_range_share": 1.0,
        }
    ]


def test_simulation_needs_enough_samples_and_is_seeded() -> None:
    few = simulate_days_on_market([10, 20], seed=3, runs=100)
    assert few.available is False and "at least 5" in (few.reason or "")
    a = simulate_days_on_market([10, 20, 30, 40, 50], seed=3, runs=500)
    b = simulate_days_on_market([10, 20, 30, 40, 50], seed=3, runs=500)
    c = simulate_days_on_market([10, 20, 30, 40, 50], seed=4, runs=500)
    assert a == b and a != c
    assert set(a.sold_within) == {"30", "60", "90"}
    assert a.sold_within["30"] <= a.sold_within["60"] <= a.sold_within["90"]
