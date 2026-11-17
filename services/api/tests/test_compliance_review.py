"""Reviewing compliance findings: decisions, appeals, the queue, superseded scans."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.ai.models import AgentRun
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.organisations import service as organisations
from app.modules.organisations.models import Organisation
from tests.test_compliance_scans import scan, scans_url
from tests.test_listings import LISTINGS, brokerage, new_listing
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here

REMARKS = "Jain families only. No bachelors."
QUEUE = "/api/v1/compliance/queue"


def finding_url(scan_id: str, index: int) -> str:
    return f"/api/v1/compliance/scans/{scan_id}/findings/{index}"


def decide(
    client: TestClient, scan_id: str, index: int, decision: str, note: str | None = None
) -> Any:
    return client.post(
        f"{finding_url(scan_id, index)}/decision", json={"decision": decision, "note": note}
    )


def appeal(client: TestClient, scan_id: str, index: int, reason: str = "It is a PG rule.") -> Any:
    return client.post(f"{finding_url(scan_id, index)}/appeal", json={"reason": reason})


def rule(
    client: TestClient, scan_id: str, index: int, decision: str, note: str = "Checked."
) -> Any:
    return client.post(
        f"{finding_url(scan_id, index)}/appeal/decision", json={"decision": decision, "note": note}
    )


@pytest.fixture
def admin(
    db: Session,
    brokerage: Brokerage,
    make_user: Callable[..., User],
    login_as: Callable[[User], TestClient],
) -> TestClient:
    """A second approver in the brokerage, to rule on appeals."""
    user = make_user("admin@a.example", name="Admin A")
    organisations.add_member(
        db, user_id=user.id, organisation_id=brokerage[0].id, role="brokerage_admin"
    )
    db.commit()
    return login_as(user)


def code(response: Any) -> str:
    result: str = response.json()["error"]["code"]
    return result


def test_decide_appeal_and_rule(db: Session, brokerage: Brokerage, admin: TestClient) -> None:
    clients = brokerage[2]
    agent, broker = clients["agent"], clients["broker"]
    listing = new_listing(agent, remarks=REMARKS)
    result = scan(db, agent, listing)
    scan_id = result["id"]
    assert [r["state"] for r in result["reviews"]] == ["open", "open"]
    assert result["review_open"] is True
    assert (result["can_review"], result["can_appeal"]) == (False, True)

    queue = broker.get(QUEUE).json()
    assert [(i["scan_id"], i["finding_index"], i["state"]) for i in queue] == [
        (scan_id, 0, "open"),
        (scan_id, 1, "open"),
    ]
    assert queue[0]["finding"]["evidence"] == "Jain families only"
    assert queue[0]["listing_title"] == listing["title"]

    # Agents do not review.
    assert decide(agent, scan_id, 0, "dismissed").status_code == 403
    assert agent.get(QUEUE).status_code == 403

    assert decide(broker, scan_id, 0, "accepted").status_code == 201
    no_note = decide(broker, scan_id, 1, "edits_requested")
    assert no_note.status_code == 422 and code(no_note) == "note_required"
    asked = decide(broker, scan_id, 1, "edits_requested", "Say 'up to 4 occupants' instead.")
    assert asked.status_code == 201
    assert asked.json()["decided_by_name"] == "Broker A"
    again = decide(broker, scan_id, 0, "dismissed")
    assert again.status_code == 409 and code(again) == "already_decided"
    assert broker.get(QUEUE).json() == []

    # Only the listing's agent appeals, once.
    assert appeal(clients["agent2"], scan_id, 1).status_code == 403
    blank = appeal(agent, scan_id, 1, reason="   ")
    assert blank.status_code == 422
    assert appeal(agent, scan_id, 1).status_code == 201
    assert code(appeal(agent, scan_id, 1)) == "already_decided"

    (waiting,) = broker.get(QUEUE).json()
    assert (waiting["finding_index"], waiting["state"]) == (1, "appealed")
    assert waiting["review"]["appeal"]["note"] == "It is a PG rule."

    # The first reviewer does not rule on their own decision.
    same = rule(broker, scan_id, 1, "overturned")
    assert same.status_code == 403 and code(same) == "same_reviewer"
    assert rule(admin, scan_id, 1, "overturned", "Fine for a PG.").status_code == 201
    assert admin.get(QUEUE).json() == []

    (latest,) = agent.get(scans_url(listing)).json()
    first, second = latest["reviews"]
    assert first["state"] == "accepted" and first["decision"]["decided_by_name"] == "Broker A"
    assert second["state"] == "overturned"
    assert second["decision"]["decision"] == "edits_requested"
    assert second["appeal"]["decided_by_name"] == "Agent A"
    assert second["appeal_decision"]["note"] == "Fine for a PG."

    # Audited with the rule and policy version; the listing is untouched.
    events = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action.like("compliance.%"), AuditEvent.action != "compliance.scan_requested"
        )
        .order_by(AuditEvent.occurred_at)
    ).all()
    assert [(e.action, e.detail["item"], e.detail["decision"]) for e in events] == [
        ("compliance.finding_decided", "0", "accepted"),
        ("compliance.finding_decided", "1", "edits_requested"),
        ("compliance.finding_appealed", "1:appeal", "appealed"),
        ("compliance.appeal_decided", "1:appeal_decision", "overturned"),
    ]
    assert all(e.detail["policy_version"] == "2026.11-1" for e in events)
    assert events[0].detail["rule_id"] == "IN-HP-01"
    assert agent.get(f"{LISTINGS}/{listing['id']}").json()["remarks"] == REMARKS


def test_what_can_be_appealed(db: Session, brokerage: Brokerage) -> None:
    agent, broker = brokerage[2]["agent"], brokerage[2]["broker"]
    scan_id = scan(db, agent, new_listing(agent, remarks=REMARKS))["id"]
    assert code(appeal(agent, scan_id, 0)) == "not_appealable"  # not decided yet
    decide(broker, scan_id, 0, "dismissed")
    assert code(appeal(agent, scan_id, 0)) == "not_appealable"
    assert code(rule(broker, scan_id, 0, "upheld")) == "no_appeal"
    assert decide(broker, scan_id, 9, "accepted").status_code == 404


def test_an_approver_does_not_review_their_own_listing(
    db: Session, brokerage: Brokerage, admin: TestClient
) -> None:
    broker = brokerage[2]["broker"]
    listing = new_listing(broker, remarks=REMARKS)  # the broker is its agent
    result = scan(db, broker, listing)
    assert (result["can_review"], result["can_appeal"]) == (False, True)
    assert decide(broker, result["id"], 0, "dismissed").status_code == 403
    assert broker.get(QUEUE).json() == []
    assert len(admin.get(QUEUE).json()) == 2


def test_a_newer_scan_replaces_the_older_review(db: Session, brokerage: Brokerage) -> None:
    agent, broker = brokerage[2]["agent"], brokerage[2]["broker"]
    listing = new_listing(agent, remarks=REMARKS)
    old = scan(db, agent, listing)
    new = scan(db, agent, listing)
    stale = decide(broker, old["id"], 0, "accepted")
    assert stale.status_code == 409 and code(stale) == "scan_superseded"
    newest, older = agent.get(scans_url(listing)).json()
    assert (newest["review_open"], older["review_open"]) == (True, False)
    assert {i["scan_id"] for i in broker.get(QUEUE).json()} == {new["id"]}


def test_clean_text_needs_no_review(db: Session, brokerage: Brokerage) -> None:
    agent, broker = brokerage[2]["agent"], brokerage[2]["broker"]
    result = scan(db, agent, new_listing(agent, remarks="Sunny 2 BHK near the lake."))
    assert result["output"]["findings"] == [] and result["reviews"] == []
    assert result["review_open"] is False
    assert broker.get(QUEUE).json() == []


def test_another_organisation_cannot_review(
    db: Session,
    brokerage: Brokerage,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    agent = brokerage[2]["agent"]
    scan_id = scan(db, agent, new_listing(agent, remarks=REMARKS))["id"]
    outsider = make_user("outsider@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)
    assert decide(other, scan_id, 0, "dismissed").status_code == 404
    assert other.get(QUEUE).json() == []
    run_jobs(db)


def test_a_late_older_scan_does_not_replace_a_newer_one(db: Session, brokerage: Brokerage) -> None:
    agent = brokerage[2]["agent"]
    listing = new_listing(agent, remarks=REMARKS)
    newer = scan(db, agent, listing)
    late = agent.post(scans_url(listing)).json()
    # Make the queued scan the older one, as if its job had been retried for a long time.
    db.execute(
        update(AgentRun)
        .where(AgentRun.id == UUID(late["id"]))
        .values(created_at=AgentRun.created_at - timedelta(hours=1))
    )
    run_jobs(db)
    states = {s["id"]: s["review_open"] for s in agent.get(scans_url(listing)).json()}
    assert states == {newer["id"]: True, late["id"]: False}
