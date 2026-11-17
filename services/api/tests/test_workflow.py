"""Workflow core (Sprint 15): the LangGraph run over the listing steps."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.ai import service as ai_service
from app.modules.ai.models import AgentRun
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.jobs.models import Job
from app.modules.organisations.models import Organisation
from app.modules.workflow import service
from app.modules.workflow.models import WorkflowRun
from tests.test_ai_extraction import FakeProvider, listing_with_photo, skip_backoff, use
from tests.test_listings import LISTINGS, brokerage, new_listing
from tests.test_media import Brokerage
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here


def start(client: TestClient, listing: dict[str, Any], **headers: str) -> dict[str, Any]:
    response = client.post(f"{LISTINGS}/{listing['id']}/workflows", headers=headers)
    assert response.status_code == 202, response.text
    result: dict[str, Any] = response.json()
    return result


def drain(db: Session, rounds: int = 20) -> None:
    """Run jobs, including the delayed re-checks, until nothing is due."""
    for _ in range(rounds):
        run_jobs(db)
        skip_backoff(db)
        if not db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")):
            return


def fetch(client: TestClient, run: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/api/v1/workflows/{run['id']}").json()
    return result


def decide_all(db: Session, client: TestClient, run: dict[str, Any]) -> None:
    """Accept every photo suggestion of the run's extraction, through the API."""
    extract = next(s for s in run["steps"] if s["name"] == "extract")
    agent_run = db.get_one(AgentRun, UUID(extract["output"]["agent_run_id"]))
    for key in ai_service.items(agent_run):
        response = client.post(
            f"/api/v1/ai/runs/{agent_run.id}/decisions",
            json={"item_key": key, "decision": "accepted"},
        )
        assert response.status_code == 201, response.text


def steps(run: dict[str, Any]) -> dict[str, str]:
    return {step["name"]: step["status"] for step in run["steps"]}


def test_run_goes_through_every_step_and_carries_the_trace(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])

    run = start(clients["agent"], listing, **{"X-Request-ID": "trace-abc-123"})
    assert run["status"] == "queued"
    assert [s["name"] for s in run["steps"]] == list(service.STEPS)
    assert run["trace_id"] == "trace-abc-123"

    drain(db)
    run = fetch(clients["agent"], run)
    # Paused: the photo suggestions wait for a person; nothing after review has run.
    assert run["status"] == "awaiting_review", run
    assert steps(run)["review"] == "waiting"
    assert steps(run)["index"] == steps(run)["valuation"] == "pending"
    review_step = next(s for s in run["steps"] if s["name"] == "review")
    assert "photo suggestions" in review_step["output"]["reason"]

    decide_all(db, clients["agent"], run)
    drain(db)
    run = fetch(clients["agent"], run)
    assert run["status"] == "succeeded", run
    assert steps(run) == {
        "geocode": "succeeded",
        "extract": "succeeded",
        "compliance": "succeeded",
        "review": "succeeded",
        "index": "succeeded",
        "valuation": "succeeded",
    }
    by_name = {s["name"]: s for s in run["steps"]}
    assert by_name["extract"]["output"]["provider"] == "fake"
    assert by_name["valuation"]["output"]["status"] == "insufficient_data"

    # Every job the run started, down to the agent calls, carries the request's trace ID.
    kinds = {
        job.kind
        for job in db.scalars(select(Job).where(Job.payload["trace_id"].astext == "trace-abc-123"))
    }
    assert {"workflow.advance", "ai.extract", "compliance.scan"} <= kinds


def test_listing_without_photos_skips_extraction(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    run = start(clients["agent"], listing)
    drain(db)
    run = fetch(clients["agent"], run)
    assert run["status"] == "succeeded"
    extract = next(s for s in run["steps"] if s["name"] == "extract")
    assert extract["status"] == "skipped"
    assert "photo" in extract["output"]["reason"].lower()


def test_one_run_at_a_time_and_permissions(
    db: Session,
    brokerage: Brokerage,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    path = f"{LISTINGS}/{listing['id']}/workflows"

    assert clients["api"].post(path).status_code == 403
    run = start(clients["agent"], listing)
    second = clients["agent"].post(path)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "workflow_in_progress"

    outsider = make_user("admin@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)
    assert other.post(path).status_code == 404
    assert other.get(path).status_code == 404
    assert other.get(f"/api/v1/workflows/{run['id']}").status_code == 404

    listed = clients["broker"].get(path).json()
    assert [r["id"] for r in listed] == [run["id"]]


def test_passes_are_idempotent(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])
    run = start(clients["agent"], listing)
    run_id = UUID(run["id"])
    # Three extra passes before any agent work: still one extraction run and one scan.
    for _ in range(3):
        service.enqueue_pass(db, db.get_one(WorkflowRun, run_id))
    drain(db)

    assert fetch(clients["agent"], run)["status"] == "awaiting_review"
    agents = db.scalars(
        select(AgentRun.agent).where(AgentRun.listing_id == UUID(listing["id"]))
    ).all()
    assert sorted(agents) == ["compliance", "vision_extraction"]


def test_a_broken_step_is_retried_then_fails_the_run(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    calls: list[int] = []

    def broken(_: service.StepContext) -> service.Outcome:
        calls.append(1)
        raise RuntimeError("index unavailable")

    monkeypatch.setitem(service.STEP_FUNCTIONS, "index", broken)
    run = start(clients["agent"], new_listing(clients["agent"]))
    drain(db)

    run = fetch(clients["agent"], run)
    assert len(calls) == service.MAX_STEP_ATTEMPTS
    assert run["status"] == "failed"
    index = next(s for s in run["steps"] if s["name"] == "index")
    assert index["status"] == "failed"
    assert index["attempts"] == service.MAX_STEP_ATTEMPTS
    assert "index unavailable" in run["error"]
    assert steps(run)["valuation"] == "succeeded"  # independent steps still ran


def test_run_that_outlives_its_budget_fails(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    run = start(clients["agent"], new_listing(clients["agent"]))
    db.execute(update(WorkflowRun).values(max_passes=1))
    db.commit()
    # Pass 1 leaves the geocode waiting; the geocode job is not run before pass 2.
    run_one_kind(db, "workflow.advance")
    skip_backoff(db)
    run_one_kind(db, "workflow.advance")

    run = fetch(clients["agent"], run)
    assert run["status"] == "failed"
    assert "budget" in run["error"]


def run_one_kind(db: Session, kind: str) -> None:
    """Run the due jobs of one kind only, holding the others back."""
    db.execute(update(Job).where(Job.kind != kind, Job.status == "queued").values(status="failed"))
    run_jobs(db)
    db.execute(
        update(Job)
        .where(Job.kind != kind, Job.status == "failed", Job.finished_at.is_(None))
        .values(status="queued")
    )
    db.commit()


# --- Sprint 16: review gate, publication gate, cancel, retry, monitor -----------------------


def submit(client: TestClient, listing: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"{LISTINGS}/{listing['id']}/transitions",
        json={"to": "pending_review", "version": listing["version"]},
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def approve(client: TestClient, listing: dict[str, Any]) -> Any:
    current = client.get(f"{LISTINGS}/{listing['id']}").json()
    return client.post(
        f"{LISTINGS}/{listing['id']}/transitions",
        json={"to": "active", "version": current["version"]},
    )


def test_approval_waits_for_the_workflow_and_its_review(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])
    run = start(clients["agent"], listing)
    listing = submit(clients["agent"], listing)

    refused = approve(clients["broker"], listing)  # run still queued
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "workflow_in_progress"

    drain(db)
    paused = approve(clients["broker"], listing)  # paused for the photo suggestions
    assert paused.status_code == 409
    assert "review" in paused.json()["error"]["message"]

    decide_all(db, clients["agent"], fetch(clients["agent"], run))
    drain(db)
    assert fetch(clients["agent"], run)["status"] == "succeeded"
    assert approve(clients["broker"], listing).status_code == 200


def test_gate_holds_outside_the_router_too(db: Session, brokerage: Brokerage) -> None:
    """The guards live in the listings service, so no caller can skip them."""
    from app.core.errors import AppError
    from app.modules.listings import service as listings
    from app.modules.listings.schemas import TransitionRequest
    from tests.test_ai_review import ctx_for

    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    start(clients["agent"], listing)
    listing = submit(clients["agent"], listing)
    with pytest.raises(AppError) as raised:
        listings.transition_listing(
            db,
            ctx_for(brokerage, "broker"),
            UUID(listing["id"]),
            TransitionRequest(to="active", version=listing["version"]),
        )
    assert raised.value.code == "workflow_in_progress"


def test_cancel_then_retry_keeps_finished_steps(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    calls: list[int] = []

    def flaky(_: service.StepContext) -> service.Outcome:
        calls.append(1)
        if len(calls) <= service.MAX_STEP_ATTEMPTS:
            raise RuntimeError("index unavailable")
        return service.Outcome("succeeded", {"indexed": True})

    monkeypatch.setitem(service.STEP_FUNCTIONS, "index", flaky)
    listing = new_listing(clients["agent"])
    run = start(clients["agent"], listing)
    drain(db)
    assert fetch(clients["agent"], run)["status"] == "failed"

    # Only editors control runs; only unfinished runs cancel; only failed ones retry.
    assert clients["api"].post(f"/api/v1/workflows/{run['id']}/retry").status_code == 403
    assert clients["agent"].post(f"/api/v1/workflows/{run['id']}/cancel").status_code == 409
    retried = clients["agent"].post(f"/api/v1/workflows/{run['id']}/retry")
    assert retried.status_code == 202, retried.text
    assert retried.json()["status"] == "queued"
    assert steps(retried.json())["geocode"] == "succeeded"  # kept
    assert steps(retried.json())["index"] == "pending"
    drain(db)
    assert fetch(clients["agent"], run)["status"] == "succeeded"

    second = start(clients["agent"], listing)
    cancelled = clients["agent"].post(f"/api/v1/workflows/{second['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    drain(db)  # the queued pass finds the run cancelled and does nothing
    assert fetch(clients["agent"], second)["passes"] == 0
    events = db.scalars(select(AuditEvent.action).where(AuditEvent.action.like("workflow.%"))).all()
    assert {"workflow.started", "workflow.retried", "workflow.cancelled"} <= set(events)


def test_monitor_lists_runs_and_failed_jobs(
    db: Session,
    brokerage: Brokerage,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    org, _, clients = brokerage
    listing = new_listing(clients["agent"])
    run = start(clients["agent"], listing)

    active = clients["agent"].get("/api/v1/workflows", params={"status": "active"}).json()
    assert [(r["id"], r["listing_title"]) for r in active] == [(run["id"], listing["title"])]
    assert clients["agent"].get("/api/v1/workflows", params={"status": "nope"}).status_code == 422
    drain(db)
    assert clients["agent"].get("/api/v1/workflows", params={"status": "active"}).json() == []

    outsider = make_user("admin@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    assert login_as(outsider).get("/api/v1/workflows").json() == []

    failed = Job(kind="test.broken", organisation_id=org.id, status="failed", last_error="boom")
    db.add(failed)
    db.commit()
    assert clients["agent"].get("/api/v1/jobs").status_code == 403  # admins only
    admin = clients["broker"]  # a broker has no audit:read either
    assert admin.get("/api/v1/jobs").status_code == 403
    assert login_as(outsider).post(f"/api/v1/jobs/{failed.id}/retry").status_code == 404


def test_admin_retries_a_failed_job(
    db: Session,
    brokerage: Brokerage,
    make_user: Callable[..., User],
    login_as: Callable[[User], TestClient],
) -> None:
    from app.modules.organisations.models import Membership

    org, _, _ = brokerage
    admin_user = make_user("boss@a.example")
    db.add(Membership(user_id=admin_user.id, organisation_id=org.id, role="brokerage_admin"))
    failed = Job(
        kind="test.broken", organisation_id=org.id, status="failed", last_error="boom", attempts=3
    )
    db.add(failed)
    db.commit()
    admin = login_as(admin_user)

    listed = admin.get("/api/v1/jobs", params={"status": "failed"}).json()
    assert [(j["id"], j["last_error"]) for j in listed] == [(str(failed.id), "boom")]
    retried = admin.post(f"/api/v1/jobs/{failed.id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert admin.post(f"/api/v1/jobs/{failed.id}/retry").status_code == 409


def test_policy_findings_pause_the_run_until_decided(db: Session, brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"], remarks="Jain families only, close to the metro.")
    run = start(clients["agent"], listing)
    drain(db)
    run = fetch(clients["agent"], run)
    assert run["status"] == "awaiting_review"
    review_step = next(s for s in run["steps"] if s["name"] == "review")
    assert "policy findings" in review_step["output"]["reason"]

    scan_id = next(s for s in run["steps"] if s["name"] == "compliance")["output"]["agent_run_id"]
    scan = clients["broker"].get(f"{LISTINGS}/{listing['id']}/compliance/scans").json()[0]
    assert scan["id"] == scan_id
    for index in range(len(scan["output"]["findings"])):
        response = clients["broker"].post(
            f"/api/v1/compliance/scans/{scan_id}/findings/{index}/decision",
            json={"decision": "dismissed"},
        )
        assert response.status_code == 201, response.text
    drain(db)
    assert fetch(clients["agent"], run)["status"] == "succeeded"


def test_an_agent_run_whose_job_died_fails_the_step(db: Session, brokerage: Brokerage) -> None:
    """A job can fail without updating its agent run (a worker without the handler)."""
    _, _, clients = brokerage
    run = start(clients["agent"], new_listing(clients["agent"]))
    run_one_kind(db, "workflow.advance")  # starts the scan (and runs it)
    db.execute(update(AgentRun).values(status="queued", output=None, finished_at=None))
    db.execute(
        update(Job)
        .where(Job.kind == "compliance.scan")
        .values(status="failed", last_error="LookupError: No handler")
    )
    db.commit()
    drain(db)
    run = fetch(clients["agent"], run)
    compliance = next(s for s in run["steps"] if s["name"] == "compliance")
    assert compliance["status"] == "failed"
    assert "No handler" in compliance["error"]
