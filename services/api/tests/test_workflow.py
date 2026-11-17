"""Workflow core (Sprint 15): the LangGraph run over the listing steps."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.ai.models import AgentRun
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
    assert run["status"] == "succeeded", run
    assert steps(run) == {
        "geocode": "succeeded",
        "extract": "succeeded",
        "compliance": "succeeded",
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

    assert fetch(clients["agent"], run)["status"] == "succeeded"
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
