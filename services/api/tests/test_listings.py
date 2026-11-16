"""Properties and listings (Module 2): lifecycle, search, permissions, tenant isolation."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.organisations.models import Organisation

PROPERTIES = "/api/v1/properties"
LISTINGS = "/api/v1/listings"

MakeUser = Callable[..., User]
MakeOrg = Callable[..., Organisation]
LoginAs = Callable[[User], TestClient]


def property_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "property_type": "apartment",
        "address": {
            "line1": "12 Lake Road",
            "locality": "Powai",
            "city": "Mumbai",
            "country": "IN",
        },
        "bedrooms": 3,
        "bathrooms": 2,
        "area": {"value": "1250.50", "unit": "sqft"},
    }
    body.update(overrides)
    return body


def new_listing(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """Create a property and a draft listing on it; return the listing."""
    prop = overrides.pop("property", None) or property_body()
    created = client.post(PROPERTIES, json=prop)
    assert created.status_code == 201, created.text
    body = {
        "property_id": created.json()["id"],
        "listing_type": "sale",
        "title": "Lake-view apartment",
        "list_price": {"amount": "25000000.00", "currency": "INR"},
        **overrides,
    }
    response = client.post(LISTINGS, json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def move(client: TestClient, listing: dict[str, Any], to: str, **extra: Any) -> dict[str, Any]:
    """Transition and return the updated listing; asserts success."""
    response = client.post(
        f"{LISTINGS}/{listing['id']}/transitions",
        json={"to": to, "version": listing["version"], **extra},
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def publish(agent: TestClient, broker: TestClient, **overrides: Any) -> dict[str, Any]:
    listing = move(agent, new_listing(agent, **overrides), "pending_review")
    return move(broker, listing, "active")


@pytest.fixture
def brokerage(
    make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> tuple[Organisation, dict[str, User], dict[str, TestClient]]:
    users = {
        role: make_user(f"{role}@a.example", name=f"{role.title()} A")
        for role in ("agent", "agent2", "broker", "api")
    }
    org = make_org(
        "Brokerage A",
        {
            users["agent"]: "agent",
            users["agent2"]: "agent",
            users["broker"]: "broker",
            users["api"]: "api_consumer",
        },
    )
    return org, users, {role: login_as(user) for role, user in users.items()}


def test_agent_creates_listing_linked_to_property_agent_and_brokerage(
    db: Session, brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]]
) -> None:
    org, users, clients = brokerage

    listing = new_listing(clients["agent"])

    assert listing["status"] == "draft"
    assert listing["organisation_id"] == str(org.id)
    assert listing["organisation_name"] == "Brokerage A"
    assert listing["listing_agent"] == {"user_id": str(users["agent"].id), "full_name": "Agent A"}
    # Money and area are exact decimals with their currency and unit, serialised as strings.
    assert listing["list_price"] == {"amount": "25000000.00", "currency": "INR"}
    assert listing["property"]["area"] == {"value": "1250.50", "unit": "sqft"}
    assert listing["property"]["address"]["city"] == "Mumbai"
    assert listing["visibility"] == "private"
    assert listing["can_edit"] is True
    assert listing["allowed_transitions"] == ["pending_review", "withdrawn"]

    fetched = clients["agent"].get(f"{LISTINGS}/{listing['id']}").json()
    assert fetched == listing
    actions = set(db.scalars(select(AuditEvent.action)))
    assert {"property.created", "listing.created"} <= actions


def test_one_property_can_have_several_listings(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]],
) -> None:
    agent = brokerage[2]["agent"]
    first = new_listing(agent)
    second = agent.post(
        LISTINGS,
        json={
            "property_id": first["property"]["id"],
            "listing_type": "rent",
            "title": "Same flat, to let",
            "list_price": {"amount": "85000", "currency": "INR"},
        },
    ).json()
    assert second["property"]["id"] == first["property"]["id"]
    # The response shows the stored amount, the same as a later read would.
    assert second["list_price"]["amount"] == "85000.00"
    assert second["id"] != first["id"]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"list_price": {"amount": "-1", "currency": "INR"}}, "body.list_price.amount"),
        ({"list_price": {"amount": "10.999", "currency": "INR"}}, "body.list_price.amount"),
        ({"list_price": {"amount": "100", "currency": "rupees"}}, "body.list_price.currency"),
        ({"title": "   "}, "body.title"),
        ({"listing_type": "auction"}, "body.listing_type"),
        ({"visibility": "public"}, "body.visibility"),
    ],
)
def test_invalid_listing_data_is_rejected_with_the_field_named(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]],
    change: dict[str, Any],
    field: str,
) -> None:
    agent = brokerage[2]["agent"]
    property_id = agent.post(PROPERTIES, json=property_body()).json()["id"]
    body = {
        "property_id": property_id,
        "listing_type": "sale",
        "title": "A flat",
        "list_price": {"amount": "100", "currency": "INR"},
        **change,
    }
    response = agent.post(LISTINGS, json=body)
    assert response.status_code == 422
    assert field in {d["field"] for d in response.json()["error"]["details"]}


def test_invalid_property_data_is_rejected(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]],
) -> None:
    agent = brokerage[2]["agent"]
    for bad in (
        property_body(property_type="castle"),
        property_body(bedrooms=-1),
        property_body(area={"value": "1200"}),  # an area needs its unit
        property_body(area={"value": "0", "unit": "sqm"}),
        property_body(address={"line1": "1 Road", "city": "Pune", "country": "India"}),
    ):
        assert agent.post(PROPERTIES, json=bad).status_code == 422, bad


def test_status_lifecycle_and_history(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]],
) -> None:
    _, users, clients = brokerage
    agent, broker = clients["agent"], clients["broker"]
    listing = new_listing(agent)
    url = f"{LISTINGS}/{listing['id']}/transitions"

    # A draft cannot jump straight to active or sold.
    for target in ("active", "temporarily_off_market", "expired"):
        skipped = agent.post(url, json={"to": target, "version": listing["version"]})
        assert skipped.status_code == 409
        assert skipped.json()["error"]["code"] == "invalid_transition"

    listing = move(agent, listing, "pending_review", reason="Ready for review")
    # An agent may not approve their own listing; the option is not even offered.
    assert "active" not in listing["allowed_transitions"]
    denied = agent.post(url, json={"to": "active", "version": listing["version"]})
    assert denied.status_code == 403

    listing = move(broker, listing, "active")
    assert listing["listed_at"] is not None
    listing = move(agent, listing, "temporarily_off_market")
    listing = move(agent, listing, "active")  # returning to market needs no second approval

    # Marking sold needs a price, in the listing's currency.
    no_price = agent.post(url, json={"to": "sold", "version": listing["version"]})
    assert no_price.status_code == 422
    wrong_currency = agent.post(
        url,
        json={
            "to": "sold",
            "version": listing["version"],
            "sold_price": {"amount": "1", "currency": "USD"},
        },
    )
    assert wrong_currency.status_code == 422
    listing = move(agent, listing, "sold", sold_price={"amount": "24000000", "currency": "INR"})
    assert listing["sold_price"] == {"amount": "24000000.00", "currency": "INR"}
    assert listing["list_price"]["amount"] == "25000000.00"  # asking price is kept separately
    assert listing["closed_at"] is not None
    assert listing["allowed_transitions"] == []  # sold is final
    edit = agent.patch(
        f"{LISTINGS}/{listing['id']}", json={"version": listing["version"], "title": "New"}
    )
    assert edit.status_code == 409

    history = agent.get(f"{LISTINGS}/{listing['id']}/history").json()["items"]
    assert [(h["from_status"], h["to_status"]) for h in reversed(history)] == [
        (None, "draft"),
        ("draft", "pending_review"),
        ("pending_review", "active"),
        ("active", "temporarily_off_market"),
        ("temporarily_off_market", "active"),
        ("active", "sold"),
    ]
    by_status = {h["to_status"]: h for h in history}
    assert by_status["pending_review"]["reason"] == "Ready for review"
    assert by_status["pending_review"]["changed_by_user_id"] == str(users["agent"].id)
    assert by_status["sold"]["changed_by_user_id"] == str(users["agent"].id)


def test_edit_rules_and_optimistic_concurrency(
    db: Session, brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]]
) -> None:
    _, users, clients = brokerage
    listing = new_listing(clients["agent"])
    url = f"{LISTINGS}/{listing['id']}"

    updated = (
        clients["agent"]
        .patch(
            url,
            json={
                "version": listing["version"],
                "list_price": {"amount": "24500000", "currency": "INR"},
                "remarks": "Price reduced",
            },
        )
        .json()
    )
    assert updated["list_price"]["amount"] == "24500000.00"
    assert updated["title"] == listing["title"]  # fields not sent are untouched
    assert updated["version"] == listing["version"] + 1
    change = db.scalars(select(AuditEvent).where(AuditEvent.action == "listing.updated")).one()
    assert change.detail["changes"]["list_price_amount"] == ["25000000.00", "24500000"]
    assert change.detail["changes"]["remarks"] == "changed"

    # Writing with the version read before that edit is refused, not silently merged.
    stale = clients["broker"].patch(url, json={"version": listing["version"], "title": "Stale"})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    stale_move = clients["agent"].post(
        f"{url}/transitions", json={"to": "pending_review", "version": listing["version"]}
    )
    assert stale_move.status_code == 409

    # A required field cannot be cleared; an optional one can.
    v = updated["version"]
    assert clients["agent"].patch(url, json={"version": v, "title": None}).status_code == 422
    cleared = clients["agent"].patch(url, json={"version": v, "remarks": None}).json()
    assert cleared["remarks"] is None

    # Another agent cannot edit it or take it over; a broker can reassign it.
    v = cleared["version"]
    other = clients["agent2"]
    assert other.get(url).json()["can_edit"] is False
    assert other.patch(url, json={"version": v, "title": "Mine now"}).status_code == 403
    assert (
        other.post(f"{url}/transitions", json={"to": "withdrawn", "version": v}).status_code == 403
    )
    assert other.delete(url).status_code == 403
    me = {"version": v, "listing_agent_user_id": str(users["agent2"].id)}
    assert clients["agent"].patch(url, json=me).status_code == 403
    reassigned = clients["broker"].patch(url, json=me).json()
    assert reassigned["listing_agent"]["full_name"] == "Agent2 A"

    # An API consumer can read but not write.
    assert clients["api"].get(url).status_code == 200
    assert clients["api"].patch(url, json={"version": 1, "title": "x"}).status_code == 403
    assert clients["api"].post(PROPERTIES, json=property_body()).status_code == 403


def test_search_filters_sorting_and_pagination(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]],
) -> None:
    agent, broker = brokerage[2]["agent"], brokerage[2]["broker"]

    def make(title: str, price: str, city: str, beds: int, kind: str = "apartment") -> None:
        address = {"line1": "1 Road", "locality": f"{city} East", "city": city, "country": "IN"}
        new_listing(
            agent,
            title=title,
            list_price={"amount": price, "currency": "INR"},
            property=property_body(address=address, bedrooms=beds, property_type=kind),
        )

    make("Sea view flat", "30000000", "Mumbai", 3)
    make("Compact studio", "9000000", "Mumbai", 1)
    make("Garden villa", "55000000", "Pune", 4, "villa")
    make("100% corner plot", "12000000", "Pune", 0, "plot")
    publish(
        agent, broker, title="Live penthouse", list_price={"amount": "90000000", "currency": "INR"}
    )

    def titles(**params: Any) -> list[str]:
        response = agent.get(LISTINGS, params=params)
        assert response.status_code == 200, response.text
        return [item["title"] for item in response.json()["items"]]

    assert len(titles()) == 5
    assert titles(sort="price_asc")[:2] == ["Compact studio", "100% corner plot"]
    assert titles(sort="price_desc")[0] == "Live penthouse"
    assert set(titles(city="pune")) == {"Garden villa", "100% corner plot"}
    assert titles(property_type="villa") == ["Garden villa"]
    assert set(titles(min_bedrooms=3, city="Mumbai")) == {"Sea view flat", "Live penthouse"}
    assert set(titles(min_price="10000000", max_price="40000000")) == {
        "Sea view flat",
        "100% corner plot",
    }
    assert titles(status="active") == ["Live penthouse"]
    assert len(titles(status=["active", "draft"])) == 5
    assert titles(q="VILLA") == ["Garden villa"]
    assert set(titles(q="pune east")) == {"Garden villa", "100% corner plot"}
    # Wildcard characters in the search text are matched literally.
    assert titles(q="100%") == ["100% corner plot"]
    assert titles(q="%") == ["100% corner plot"]
    assert titles(scope="network") == []

    assert agent.get(LISTINGS, params={"sort": "random"}).status_code == 422

    # Paging by price visits every listing exactly once, in order.
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, Any] = {"sort": "price_asc", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = agent.get(LISTINGS, params=params).json()
        assert "items" in page, page
        seen += [item["list_price"]["amount"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ["9000000.00", "12000000.00", "30000000.00", "55000000.00", "90000000.00"]


def test_tenant_isolation_and_network_sharing(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]],
    make_user: MakeUser,
    make_org: MakeOrg,
    login_as: LoginAs,
) -> None:
    _, _, clients = brokerage
    agent, broker = clients["agent"], clients["broker"]
    outsider_user = make_user("broker@b.example")
    make_org("Brokerage B", {outsider_user: "broker"})
    outsider = login_as(outsider_user)

    private_live = publish(agent, broker, title="Private live")
    shared_draft = new_listing(agent, title="Shared draft", visibility="network")
    shared_live = publish(agent, broker, title="Shared live", visibility="network")

    # Another organisation sees only listings that are shared AND in a public status.
    assert [i["title"] for i in outsider.get(LISTINGS).json()["items"]] == ["Shared live"]
    assert outsider.get(LISTINGS, params={"scope": "organisation"}).json()["items"] == []
    for hidden in (private_live, shared_draft):
        assert outsider.get(f"{LISTINGS}/{hidden['id']}").status_code == 404
        assert outsider.get(f"{LISTINGS}/{hidden['id']}/history").status_code == 404
        patch = outsider.patch(f"{LISTINGS}/{hidden['id']}", json={"version": 1, "title": "x"})
        assert patch.status_code == 404

    # A shared listing is read-only to them, and its history and property record stay private.
    url = f"{LISTINGS}/{shared_live['id']}"
    seen = outsider.get(url).json()
    assert seen["organisation_name"] == "Brokerage A"
    assert seen["can_edit"] is False and seen["allowed_transitions"] == []
    version = seen["version"]
    assert outsider.patch(url, json={"version": version, "title": "Hijacked"}).status_code == 403
    assert (
        outsider.post(
            f"{url}/transitions", json={"to": "withdrawn", "version": version}
        ).status_code
        == 403
    )
    assert outsider.delete(url).status_code == 403
    assert outsider.get(f"{url}/history").status_code == 403
    property_url = f"{PROPERTIES}/{seen['property']['id']}"
    assert outsider.get(property_url).status_code == 404
    assert outsider.put(property_url, json={**property_body(), "version": 1}).status_code == 404
    assert outsider.delete(property_url).status_code == 404
    assert outsider.get(PROPERTIES).json()["items"] == []
    # They cannot list their own listing against another tenant's property.
    hijack = outsider.post(
        LISTINGS,
        json={
            "property_id": seen["property"]["id"],
            "listing_type": "sale",
            "title": "Not mine",
            "list_price": {"amount": "1", "currency": "INR"},
        },
    )
    assert hijack.status_code == 404
    assert agent.get(url).json()["title"] == "Shared live"

    # Withdrawing a shared listing removes it from other organisations at once.
    move(agent, agent.get(url).json(), "withdrawn")
    assert outsider.get(url).status_code == 404
    assert outsider.get(LISTINGS).json()["items"] == []
    assert agent.get(url).status_code == 200


def test_listing_agent_must_belong_to_the_organisation(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]], make_user: MakeUser
) -> None:
    broker = brokerage[2]["broker"]
    stranger = make_user("stranger@b.example")
    property_id = broker.post(PROPERTIES, json=property_body()).json()["id"]
    response = broker.post(
        LISTINGS,
        json={
            "property_id": property_id,
            "listing_type": "sale",
            "title": "A flat",
            "list_price": {"amount": "100", "currency": "INR"},
            "listing_agent_user_id": str(stranger.id),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.listing_agent_user_id"


def test_archiving_and_property_update(
    brokerage: tuple[Organisation, dict[str, User], dict[str, TestClient]],
) -> None:
    agent, broker = brokerage[2]["agent"], brokerage[2]["broker"]
    live = publish(agent, broker)
    url = f"{LISTINGS}/{live['id']}"
    property_url = f"{PROPERTIES}/{live['property']['id']}"

    # Property details are edited on the property and show on its listings.
    prop = live["property"]
    changed = agent.put(
        property_url, json={**property_body(bedrooms=4), "version": prop["version"]}
    )
    assert changed.status_code == 200 and changed.json()["bedrooms"] == 4
    assert agent.get(url).json()["property"]["bedrooms"] == 4
    stale = agent.put(property_url, json={**property_body(), "version": prop["version"]})
    assert stale.status_code == 409

    # A live listing must be withdrawn before archiving, and its property is in use until then.
    assert agent.delete(url).status_code == 409
    assert agent.delete(property_url).status_code == 409
    withdrawn = move(agent, agent.get(url).json(), "withdrawn")
    assert agent.delete(url).status_code == 204

    assert agent.get(LISTINGS).json()["items"] == []
    archived = agent.get(LISTINGS, params={"include_archived": True}).json()["items"]
    assert [item["id"] for item in archived] == [live["id"]]
    assert archived[0]["archived_at"] is not None and archived[0]["can_edit"] is False
    frozen = agent.post(
        f"{url}/transitions", json={"to": "draft", "version": withdrawn["version"] + 1}
    )
    assert frozen.status_code == 409

    assert agent.delete(property_url).status_code == 204
    assert agent.get(PROPERTIES).json()["items"] == []
    relist = agent.post(
        LISTINGS,
        json={
            "property_id": live["property"]["id"],
            "listing_type": "sale",
            "title": "Again",
            "list_price": {"amount": "1", "currency": "INR"},
        },
    )
    assert relist.status_code == 409


def test_listing_routes_require_sign_in(client: TestClient) -> None:
    assert client.get(LISTINGS).status_code == 401
    assert client.get(PROPERTIES).status_code == 401
    assert client.post(PROPERTIES, json=property_body()).status_code == 401
