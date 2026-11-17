"""Dashboard and audit view (Sprint 20)."""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.jobs import service as jobs
from app.modules.organisations import service as organisations
from app.modules.organisations.models import Organisation
from tests.test_listings import brokerage, move, new_listing
from tests.test_media import Brokerage

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here

DASHBOARD = "/api/v1/dashboard"
AUDIT = "/api/v1/audit-events"


def test_dashboard_parts_follow_permissions(
    brokerage: Brokerage,
    db: Session,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    org, _, clients = brokerage
    mine = new_listing(clients["agent"])
    move(clients["agent"], new_listing(clients["agent"]), "pending_review")
    new_listing(clients["agent2"])
    failed = jobs.enqueue(db, "test.kind", {}, organisation_id=org.id)
    failed.status = "failed"
    db.commit()

    agent = clients["agent"].get(DASHBOARD)
    assert agent.status_code == 200, agent.text
    body = agent.json()
    assert body["listings"]["organisation"]["draft"] == 2
    assert body["listings"]["organisation"]["pending_review"] == 1
    assert body["listings"]["mine"] == {"draft": 1, "pending_review": 1}
    assert body["review_queue"] is None  # agents do not review
    assert body["failed_jobs"] is None  # only administrators see the job monitor
    assert body["unread_notifications"] == 0
    assert mine["status"] == "draft"

    broker = clients["broker"].get(DASHBOARD).json()
    assert broker["review_queue"] == 0
    assert broker["listings"]["mine"] == {}

    api_user = clients["api"].get(DASHBOARD).json()
    assert api_user["listings"]["organisation"]["draft"] == 2  # listing:read only
    assert api_user["review_queue"] is None

    admin = make_user("admin@a.example", name="Admin A")
    other_admin = make_user("admin@b.example", name="Admin B")
    organisations.add_member(db, user_id=admin.id, organisation_id=org.id, role="brokerage_admin")
    db.commit()
    assert login_as(admin).get(DASHBOARD).json()["failed_jobs"] == 1

    # Another organisation sees only its own numbers.
    make_org("Brokerage B", {other_admin: "brokerage_admin"})
    other = login_as(other_admin).get(DASHBOARD).json()
    assert other["listings"]["organisation"] == {}
    assert other["failed_jobs"] == 0


def test_audit_filters_and_actor_names(
    brokerage: Brokerage,
    db: Session,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    org, users, clients = brokerage
    listing = new_listing(clients["agent"])
    move(clients["agent"], listing, "pending_review")
    admin = make_user("admin@a.example", name="Admin A")
    organisations.add_member(db, user_id=admin.id, organisation_id=org.id, role="brokerage_admin")
    db.commit()
    client = login_as(admin)

    everything = client.get(AUDIT).json()["items"]
    assert len(everything) >= 3
    listing_events = client.get(AUDIT, params={"action": "listing."}).json()["items"]
    assert listing_events and all(e["action"].startswith("listing.") for e in listing_events)

    by_agent = client.get(AUDIT, params={"actor_user_id": str(users["agent"].id)}).json()["items"]
    assert by_agent and {e["actor_name"] for e in by_agent} == {"Agent A"}
    assert by_agent[0]["actor_email"] == "agent@a.example"

    about = client.get(AUDIT, params={"target_id": listing["id"]}).json()["items"]
    assert about and {e["target_id"] for e in about} == {listing["id"]}

    # A wildcard in the prefix is matched literally.
    assert client.get(AUDIT, params={"action": "%"}).json()["items"] == []

    # Members without audit:read are refused; another organisation sees none of these.
    assert clients["broker"].get(AUDIT).status_code == 403
    outsider = make_user("admin@b.example", name="Admin B")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    assert login_as(outsider).get(AUDIT, params={"target_id": listing["id"]}).json()["items"] == []
