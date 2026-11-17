"""Listing import API (Module 6a): preview, all-or-nothing import, provenance, permissions."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.listings.models import Listing
from app.modules.organisations.models import Organisation
from tests.test_listings import LISTINGS, LoginAs, MakeOrg, MakeUser, brokerage, move

__all__ = ["brokerage"]  # pytest fixture, imported for use here

IMPORTS = "/api/v1/imports"
FIXTURES = Path(__file__).parent / "fixtures" / "imports"
Brokerage = tuple[Organisation, dict[str, User], dict[str, TestClient]]


def _file(name: str) -> dict[str, str]:
    return {"filename": name, "content": (FIXTURES / name).read_text(encoding="utf-8")}


def _listing_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Listing)) or 0


def _import(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post(IMPORTS, json=_file(name))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_preview_maps_columns_and_saves_nothing(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    response = clients["agent"].post(f"{IMPORTS}/preview", json=_file("portal.csv"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is True
    assert {"header": "BHK", "field": "bedrooms"} in body["columns"]
    assert body["rows"][0]["values"]["list_price"] == "12500000.00"
    assert body["rows"][1]["values"]["area"] == "1800 sqft"
    assert _listing_count(db) == 0

    invalid = clients["agent"].post(f"{IMPORTS}/preview", json=_file("invalid.csv")).json()
    assert invalid["ready"] is False
    errors = invalid["rows"][1]["errors"]
    assert {"field": "listing_type", "column": "Listing type"} | {
        "message": '"Swap" is not a listing type. Use sale or rent.'
    } in errors


def test_import_creates_draft_listings_with_provenance(db: Session, brokerage: Brokerage) -> None:
    org, users, clients = brokerage
    result = _import(clients["agent"], "portal.csv")
    assert [item["row_number"] for item in result["listings"]] == [2, 3, 4]
    assert result["listings"][0]["title"] == "2 BHK in Powai"

    listing = clients["agent"].get(f"{LISTINGS}/{result['listings'][0]['listing_id']}").json()
    assert listing["status"] == "draft"
    assert listing["visibility"] == "private"
    assert listing["listing_agent"]["user_id"] == str(users["agent"].id)
    assert listing["list_price"] == {"amount": "12500000.00", "currency": "INR"}
    assert listing["property"]["property_type"] == "apartment"
    assert listing["property"]["area"] == {"value": "1050.00", "unit": "sqft"}
    assert listing["property"]["address"]["postal_code"] == "400076"

    source = clients["broker"].get(f"{LISTINGS}/{listing['id']}/import-source").json()
    assert source["filename"] == "portal.csv"
    assert source["row_number"] == 2
    assert source["external_id"] == "P-101"
    assert source["source"]["Price (INR)"] == "₹1.25 Cr"

    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "listing.imported")).one()
    assert event.organisation_id == org.id
    assert event.target_id == result["id"]
    assert event.detail == {"filename": "portal.csv", "listings": 3}

    # Created by hand: no import source.
    other = db.scalars(select(Listing).where(Listing.id != listing["id"])).first()
    assert other is not None
    manual = clients["agent"].post(
        LISTINGS,
        json={
            "property_id": str(other.property_id),
            "listing_type": "sale",
            "title": "By hand",
            "list_price": {"amount": "100.00", "currency": "INR"},
        },
    )
    assert clients["agent"].get(f"{LISTINGS}/{manual.json()['id']}/import-source").json() is None


def test_file_with_errors_imports_nothing(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    response = clients["agent"].post(IMPORTS, json=_file("invalid.csv"))
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "import_invalid"
    assert "nothing was imported" in error["message"]
    assert {"field": "row 2.property_type"} | {
        "message": '"Castle" is not a known property type. '
        "Use apartment, house, villa, plot, commercial or other."
    } in error["details"]
    assert _listing_count(db) == 0


def test_same_listing_id_cannot_be_imported_twice(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    _import(clients["agent"], "reso.csv")
    again = clients["agent2"].post(IMPORTS, json=_file("reso.csv"))
    assert again.status_code == 422
    assert "already been imported" in again.json()["error"]["details"][0]["message"]
    assert _listing_count(db) == 2


def test_readers_cannot_import(brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    api = clients["api"]
    assert api.get(f"{IMPORTS}/fields").status_code == 403
    assert api.post(f"{IMPORTS}/preview", json=_file("reso.csv")).status_code == 403
    assert api.post(IMPORTS, json=_file("reso.csv")).status_code == 403


def test_fields_reference(brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    fields = {f["name"]: f for f in clients["agent"].get(f"{IMPORTS}/fields").json()}
    assert fields["list_price"]["reso_name"] == "ListPrice"
    assert fields["list_price"]["required"] is True
    assert "Asking price" in fields["list_price"]["accepted_headers"]
    assert fields["title"]["reso_name"] is None


def test_other_organisations_never_see_provenance(
    brokerage: Brokerage, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    _, _, clients = brokerage
    outsider = make_user("agent@b.example")
    make_org("Brokerage B", {outsider: "agent"})
    other = login_as(outsider)

    listing_id = _import(clients["agent"], "reso.csv")["listings"][0]["listing_id"]
    assert other.get(f"{LISTINGS}/{listing_id}/import-source").status_code == 404

    # Shared on the network, the listing is visible but where it came from is not.
    listing = clients["agent"].get(f"{LISTINGS}/{listing_id}").json()
    updated = clients["agent"].patch(
        f"{LISTINGS}/{listing_id}", json={"version": listing["version"], "visibility": "network"}
    )
    assert updated.status_code == 200, updated.text
    move(clients["broker"], move(clients["agent"], updated.json(), "pending_review"), "active")
    assert other.get(f"{LISTINGS}/{listing_id}").status_code == 200
    assert other.get(f"{LISTINGS}/{listing_id}/import-source").json() is None
