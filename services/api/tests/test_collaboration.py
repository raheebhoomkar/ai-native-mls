"""Collaboration (Sprint 19): assignment, comments, private notes, notifications, timeline."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.organisations.models import Organisation
from tests.test_listings import LISTINGS, brokerage, move, new_listing
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here

NOTES = "/api/v1/notifications"


def comment(client: TestClient, listing: dict[str, Any], body: str, **extra: Any) -> Any:
    return client.post(f"{LISTINGS}/{listing['id']}/comments", json={"body": body, **extra})


def inbox(client: TestClient) -> dict[str, Any]:
    result: dict[str, Any] = client.get(NOTES).json()
    return result


def test_assignment_notifies_the_assignee(brokerage: Brokerage) -> None:
    _, users, clients = brokerage
    listing = new_listing(clients["agent"])
    path = f"{LISTINGS}/{listing['id']}/assignment"
    assert clients["agent"].get(path).json() is None

    response = clients["agent"].put(
        path, json={"user_id": str(users["agent2"].id), "note": "Photos?"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["user_name"] == users["agent2"].full_name

    notes = inbox(clients["agent2"])
    assert notes["unread"] == 1
    assert notes["items"][0]["kind"] == "assigned"
    assert notes["items"][0]["listing_id"] == listing["id"]
    assert inbox(clients["agent"])["unread"] == 0  # the actor is not told

    # Only editors assign; only members who work on listings can be assigned.
    assert clients["agent2"].put(path, json={"user_id": None}).status_code == 403
    bad = clients["agent"].put(path, json={"user_id": str(users["api"].id)})
    assert bad.status_code == 422
    assert clients["broker"].put(path, json={"user_id": None}).json() is None
    assert clients["agent"].get(path).json() is None


def test_team_comments_and_private_notes(
    brokerage: Brokerage,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    _, users, clients = brokerage
    listing = move(
        clients["agent"], new_listing(clients["agent"], visibility="network"), "pending_review"
    )
    listing = move(clients["broker"], listing, "active")

    team = comment(clients["broker"], listing, "Price looks high for Powai.")
    assert team.status_code == 201, team.text
    private = comment(clients["agent"], listing, "Call the owner on Monday.", visibility="private")
    assert private.status_code == 201

    seen_by_agent = [
        c["body"] for c in clients["agent"].get(f"{LISTINGS}/{listing['id']}/comments").json()
    ]
    seen_by_broker = [
        c["body"] for c in clients["broker"].get(f"{LISTINGS}/{listing['id']}/comments").json()
    ]
    assert seen_by_agent == ["Price looks high for Powai.", "Call the owner on Monday."]
    assert seen_by_broker == ["Price looks high for Powai."]
    # Read-only members read team comments but cannot write.
    assert clients["api"].get(f"{LISTINGS}/{listing['id']}/comments").status_code == 200
    assert comment(clients["api"], listing, "hi").status_code == 403

    # The listing is shared with the network, but comments stay inside the organisation.
    outsider = make_user("admin@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)
    assert other.get(f"{LISTINGS}/{listing['id']}").status_code == 200
    assert other.get(f"{LISTINGS}/{listing['id']}/comments").status_code == 404
    assert comment(other, listing, "hello").status_code == 404
    assert other.get(f"{LISTINGS}/{listing['id']}/activity").status_code == 404

    # The listing agent heard about the team comment; nobody heard about the private note.
    kinds = [n["kind"] for n in inbox(clients["agent"])["items"]]
    assert kinds == ["comment"]
    assert inbox(clients["broker"])["unread"] == 0


def test_only_the_author_edits_or_deletes(brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    created = comment(clients["agent"], listing, "Frist draft").json()
    path = f"/api/v1/comments/{created['id']}"

    assert clients["broker"].patch(path, json={"body": "x"}).status_code == 403
    edited = clients["agent"].patch(path, json={"body": "First draft"})
    assert edited.json()["body"] == "First draft"
    assert edited.json()["edited_at"] is not None

    assert clients["agent"].delete(path).status_code == 204
    [gone] = clients["agent"].get(f"{LISTINGS}/{listing['id']}/comments").json()
    assert gone["body"] == ""
    assert gone["deleted_at"] is not None
    assert clients["agent"].delete(path).status_code == 404

    private = comment(clients["agent"], listing, "mine", visibility="private").json()
    assert (
        clients["broker"].patch(f"/api/v1/comments/{private['id']}", json={"body": "x"}).status_code
        == 404
    )


def test_preferences_mute_a_kind_and_read_marks(brokerage: Brokerage) -> None:
    _, users, clients = brokerage
    listing = new_listing(clients["agent"])
    prefs = clients["agent"].put(f"{NOTES}/preferences", json={"comment": False})
    assert prefs.json() == {"assigned": True, "comment": False, "workflow_finished": True}
    assert clients["agent"].put(f"{NOTES}/preferences", json={"nope": True}).status_code == 422

    comment(clients["broker"], listing, "Muted for the agent")
    assert inbox(clients["agent"])["unread"] == 0

    path = f"{LISTINGS}/{listing['id']}/assignment"
    clients["broker"].put(path, json={"user_id": str(users["agent"].id)})
    clients["broker"].put(path, json={"user_id": str(users["agent"].id), "note": "again"})
    notes = inbox(clients["agent"])
    assert notes["unread"] == 2
    first = notes["items"][0]["id"]
    assert clients["agent"].post(f"{NOTES}/{first}/read").status_code == 204
    assert inbox(clients["agent"])["unread"] == 1
    assert clients["agent"].get(NOTES, params={"unread": True}).json()["items"][0]["id"] != first
    assert clients["agent"].post(f"{NOTES}/read-all").status_code == 204
    assert inbox(clients["agent"])["unread"] == 0
    # Someone else's notification cannot be marked.
    assert clients["broker"].post(f"{NOTES}/{first}/read").status_code == 404


def test_activity_timeline_merges_events_and_comments(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    listing = move(clients["agent"], listing, "pending_review")
    comment(clients["agent"], listing, "Ready for review")
    comment(clients["agent"], listing, "Note to self", visibility="private")
    assert clients["agent"].post(f"{LISTINGS}/{listing['id']}/workflows").status_code == 202
    run_jobs(db)

    timeline = clients["agent"].get(f"{LISTINGS}/{listing['id']}/activity").json()
    summaries = [item["summary"] for item in timeline]
    assert "created the listing" in summaries
    assert "changed the status from draft to pending_review" in summaries
    assert "Ready for review" in summaries
    assert "Note to self" in summaries
    assert "started the workflow" in summaries
    assert "asked for a policy check" in summaries  # names the listing in its detail
    times = [item["at"] for item in timeline]
    assert times == sorted(times, reverse=True)

    broker_view = [
        i["summary"] for i in clients["broker"].get(f"{LISTINGS}/{listing['id']}/activity").json()
    ]
    assert "Note to self" not in broker_view


def test_finished_workflow_notifies_whoever_started_it(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    assert clients["agent"].post(f"{LISTINGS}/{listing['id']}/workflows").status_code == 202
    from tests.test_workflow import drain

    drain(db)
    drain(db)
    notes = inbox(clients["agent"])["items"]
    assert [n["kind"] for n in notes] == ["workflow_finished"]
    assert notes[0]["title"].startswith("Workflow succeeded")
