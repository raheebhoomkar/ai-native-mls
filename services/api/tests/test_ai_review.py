"""AI suggestion review (Module 4b): decisions, listing features, no silent overwrite."""

import copy
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.ai import service as ai_service
from app.modules.ai.models import AgentRun
from app.modules.audit.models import AuditEvent
from app.modules.listings import service as listings
from app.modules.listings.models import Listing
from app.modules.organisations.deps import TenantContext
from app.modules.review.models import ReviewDecision, ReviewTask
from tests.test_ai_extraction import FakeProvider, extractions, listing_with_photo, use
from tests.test_listings import LISTINGS, brokerage
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here


def ctx_for(brokerage: Brokerage, role: str) -> TenantContext:
    org, users, _ = brokerage
    membership_role = {
        "agent": "agent",
        "agent2": "agent",
        "broker": "broker",
        "api": "api_consumer",
    }
    return TenantContext(users[role], org.id, membership_role[role])


def reviewed_run(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch, *features: Any
) -> tuple[AgentRun, dict[str, Any], list[str]]:
    """A succeeded run with two suggestions on one photo."""
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])
    run_id = clients["agent"].post(extractions(listing["id"])).json()["id"]
    run_jobs(db)
    run = db.get_one(AgentRun, UUID(run_id))
    photo = copy.deepcopy(run.output["photos"][0])  # type: ignore[index]
    photo["features"].append({**photo["features"][0], "attribute": "appliance", "value": "oven"})
    run.output = {"photos": [photo]}
    db.flush()
    return run, listing, sorted(ai_service.items(run))


def key_of(run: AgentRun, attribute: str) -> str:
    return next(k for k, f in ai_service.items(run).items() if f.attribute == attribute)


def test_succeeded_run_opens_one_review_task(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, keys = reviewed_run(db, brokerage, monkeypatch)

    task = db.scalar(select(ReviewTask).where(ReviewTask.subject_id == str(run.id)))
    assert task is not None and (task.subject_type, task.status) == ("agent_run", "open")
    assert len(keys) == 2


def test_accept_edit_reject_record_decisions_and_add_features_only(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, listing_out, _ = reviewed_run(db, brokerage, monkeypatch)
    _, _, clients = brokerage
    before = clients["agent"].get(f"{LISTINGS}/{listing_out['id']}").json()
    ctx = ctx_for(brokerage, "agent")
    floor, oven = key_of(run, "flooring"), key_of(run, "appliance")

    ai_service.decide(db, ctx, run.id, item_key=floor, decision="edited", value=" Teak wood ")
    decision = ai_service.decide(db, ctx, run.id, item_key=oven, decision="rejected", note="Hob")

    assert (decision.decision, decision.final, decision.note) == ("rejected", None, "Hob")
    edited = db.scalar(select(ReviewDecision).where(ReviewDecision.item_key == floor))
    assert edited is not None and edited.suggested["value"] == "hardwood"
    assert edited.final == {"attribute": "flooring", "value": "Teak wood"}
    listing = db.get_one(Listing, UUID(listing_out["id"]))
    features = listings.list_features(db, listing)
    assert [(f.attribute, f.value, f.source) for f in features] == [
        ("flooring", "Teak wood", "ai_reviewed")
    ]
    assert str(features[0].media_asset_id) == floor.split(":")[0]
    # Agent-entered listing data is untouched; the task is finished.
    assert clients["agent"].get(f"{LISTINGS}/{listing_out['id']}").json() == before
    task = db.scalar(select(ReviewTask).where(ReviewTask.subject_id == str(run.id)))
    assert task is not None and task.status == "closed" and task.closed_at


def test_accept_keeps_the_suggested_value(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, listing_out, keys = reviewed_run(db, brokerage, monkeypatch)
    key = key_of(run, "flooring")

    ai_service.decide(db, ctx_for(brokerage, "agent"), run.id, item_key=key, decision="accepted")

    listing = db.get_one(Listing, UUID(listing_out["id"]))
    assert [f.value for f in listings.list_features(db, listing)] == ["hardwood"]
    task = db.scalar(select(ReviewTask).where(ReviewTask.subject_id == str(run.id)))
    assert task is not None and task.status == "open"  # one suggestion left


def test_a_decision_is_never_replaced(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, [key, _] = reviewed_run(db, brokerage, monkeypatch)
    ctx = ctx_for(brokerage, "agent")
    ai_service.decide(db, ctx, run.id, item_key=key, decision="rejected")

    with pytest.raises(AppError) as raised:
        ai_service.decide(db, ctx, run.id, item_key=key, decision="accepted")

    assert (raised.value.status_code, raised.value.code) == (409, "already_decided")
    assert len(db.scalars(select(ReviewDecision)).all()) == 1


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"item_key": "nope:0", "decision": "accepted"}, 404),
        ({"decision": "edited", "value": "  "}, 422),
        ({"decision": "edited", "value": "x" * 121}, 422),
    ],
)
def test_bad_items_and_values_are_refused(
    db: Session,
    brokerage: Brokerage,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    status: int,
) -> None:
    run, _, [key, _] = reviewed_run(db, brokerage, monkeypatch)
    kwargs = {"item_key": key, **kwargs}

    with pytest.raises(AppError) as raised:
        ai_service.decide(db, ctx_for(brokerage, "agent"), run.id, **kwargs)

    assert raised.value.status_code == status


def test_readers_and_other_organisations_cannot_decide(
    db: Session,
    brokerage: Brokerage,
    monkeypatch: pytest.MonkeyPatch,
    make_user: Any,
    make_org: Any,
) -> None:
    run, _, [key, _] = reviewed_run(db, brokerage, monkeypatch)
    for role in ("api", "agent2"):
        with pytest.raises(AppError) as raised:
            ai_service.decide(
                db, ctx_for(brokerage, role), run.id, item_key=key, decision="accepted"
            )
        assert raised.value.status_code == 403, role
    outsider = make_user("admin@b.example")
    other = make_org("Brokerage B", {outsider: "brokerage_admin"})
    with pytest.raises(AppError) as raised:
        ai_service.decide(
            db,
            TenantContext(outsider, other.id, "brokerage_admin"),
            run.id,
            item_key=key,
            decision="accepted",
        )
    assert raised.value.status_code == 404
    assert db.scalar(select(ReviewDecision)) is None


def test_the_same_feature_is_kept_once(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, listing_out, _ = reviewed_run(db, brokerage, monkeypatch)
    listing = db.get_one(Listing, UUID(listing_out["id"]))
    ctx = ctx_for(brokerage, "agent")

    for value in ("Hardwood", "HARDWOOD"):
        listings.add_feature(
            db, ctx, listing, attribute="flooring", value=value, media_asset_id=None
        )

    assert [f.value for f in listings.list_features(db, listing)] == ["Hardwood"]


# --- API -------------------------------------------------------------------------------------


def decisions_url(run: AgentRun) -> str:
    return f"/api/v1/ai/runs/{run.id}/decisions"


def test_api_decision_is_shown_on_the_run_and_as_a_feature(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, listing, _ = reviewed_run(db, brokerage, monkeypatch)
    _, _, clients = brokerage
    floor = key_of(run, "flooring")

    response = clients["agent"].post(
        decisions_url(run), json={"item_key": floor, "decision": "edited", "value": "Teak"}
    )

    assert response.status_code == 201, response.text
    assert response.json()["final_value"] == "Teak"
    [run_out] = clients["agent"].get(extractions(listing["id"])).json()
    assert run_out["can_review"] is True
    assert run_out["decisions"][floor]["decision"] == "edited"
    features = clients["agent"].get(f"{LISTINGS}/{listing['id']}/features").json()
    assert [(f["attribute"], f["value"]) for f in features] == [("flooring", "Teak")]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "ai.suggestion_decided"))
    assert event is not None and event.detail == {"item_key": floor, "decision": "edited"}
    again = clients["agent"].post(
        decisions_url(run), json={"item_key": floor, "decision": "rejected"}
    )
    assert again.status_code == 409


def test_api_readers_see_decisions_but_cannot_decide(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, listing, [key, _] = reviewed_run(db, brokerage, monkeypatch)
    _, _, clients = brokerage

    for role in ("api", "agent2"):
        response = clients[role].post(
            decisions_url(run), json={"item_key": key, "decision": "accepted"}
        )
        assert response.status_code == 403, role
    [run_out] = clients["agent2"].get(extractions(listing["id"])).json()
    assert (run_out["can_review"], run_out["decisions"]) == (False, {})
    assert clients["agent2"].get(f"{LISTINGS}/{listing['id']}/features").json() == []


def test_api_bad_body_and_unknown_run(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, [key, _] = reviewed_run(db, brokerage, monkeypatch)
    _, _, clients = brokerage

    bad = clients["agent"].post(decisions_url(run), json={"item_key": key, "decision": "maybe"})
    edit = clients["agent"].post(decisions_url(run), json={"item_key": key, "decision": "edited"})
    missing = clients["agent"].post(
        f"/api/v1/ai/runs/{uuid4()}/decisions", json={"item_key": key, "decision": "accepted"}
    )

    assert (bad.status_code, edit.status_code, missing.status_code) == (422, 422, 404)
