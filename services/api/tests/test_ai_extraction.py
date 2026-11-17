"""AI extraction (Module 4): request, background run, retries, permissions, tenant isolation."""

from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.ai import service as ai_service
from app.modules.ai.models import AgentRun
from app.modules.ai.providers import (
    DemoVisionProvider,
    MalformedOutput,
    Photo,
    ProviderRejected,
    ProviderResult,
    ProviderUnavailable,
)
from app.modules.ai.schemas import Extraction, Feature, PhotoExtraction
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.organisations.models import Organisation
from tests.test_listings import LISTINGS, brokerage, new_listing
from tests.test_media import Brokerage, upload
from tests.test_media_processing import image_bytes, run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here


class FakeProvider:
    """Answers with one feature per photo, or raises the queued errors first."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls: list[Sequence[Photo]] = []

    def extract(self, photos: Sequence[Photo]) -> ProviderResult:
        self.calls.append(photos)
        if self.errors:
            raise self.errors.pop(0)
        extraction = Extraction(
            photos=[
                PhotoExtraction(
                    media_asset_id=photo.media_asset_id,
                    features=[
                        Feature(
                            attribute="flooring",
                            value="hardwood",
                            confidence=0.9,
                            evidence="Wood planks across the floor.",
                        )
                    ],
                )
                for photo in photos
            ]
        )
        return ProviderResult(
            extraction=extraction, provider="fake", model="fake-1", model_version="2026"
        )


def use(monkeypatch: pytest.MonkeyPatch, provider: Any) -> Any:
    monkeypatch.setattr(ai_service, "get_provider", lambda: provider)
    return provider


def extractions(listing_id: str) -> str:
    return f"{LISTINGS}/{listing_id}/ai/extractions"


def listing_with_photo(db: Session, client: TestClient) -> dict[str, Any]:
    listing = new_listing(client)
    assert upload(client, listing["id"], image_bytes()).status_code == 201
    run_jobs(db)  # thumbnail made, photo ready
    return listing


def skip_backoff(db: Session) -> None:
    db.execute(update(Job).values(run_after=Job.created_at))


def test_editor_requests_extraction_and_worker_stores_output(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, users, clients = brokerage
    provider = use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])
    before = clients["agent"].get(f"{LISTINGS}/{listing['id']}").json()

    response = clients["agent"].post(extractions(listing["id"]))

    assert response.status_code == 202, response.text
    run = response.json()
    assert (run["status"], run["agent"], run["output"], run["is_demo"]) == (
        "queued",
        "vision_extraction",
        None,
        False,
    )
    [photo] = clients["agent"].get(f"{LISTINGS}/{listing['id']}/media").json()
    assert run["inputs"] == [{"media_asset_id": photo["id"], "sha256": photo["sha256"]}]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "ai.extraction_requested"))
    assert event is not None and event.target_id == run["id"]
    assert event.actor_user_id == users["agent"].id

    run_jobs(db)

    [done] = clients["agent"].get(extractions(listing["id"])).json()
    assert (done["status"], done["provider"], done["model"], done["model_version"]) == (
        "succeeded",
        "fake",
        "fake-1",
        "2026",
    )
    assert done["output"]["photos"][0]["media_asset_id"] == photo["id"]
    assert done["output"]["photos"][0]["features"][0]["value"] == "hardwood"
    assert done["started_at"] and done["finished_at"]
    assert [p.media_asset_id for p in provider.calls[0]] == [UUID(photo["id"])]
    # Suggestions stay on the run; the listing itself is untouched.
    assert clients["agent"].get(f"{LISTINGS}/{listing['id']}").json() == before


def test_runs_are_listed_newest_first(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])
    first = clients["agent"].post(extractions(listing["id"])).json()
    second = clients["agent"].post(extractions(listing["id"])).json()
    # The test shares one transaction, so now() is the same for both; age the first.
    db.execute(
        update(AgentRun)
        .where(AgentRun.id == UUID(first["id"]))
        .values(created_at=AgentRun.created_at - timedelta(minutes=1))
    )

    listed = clients["agent"].get(extractions(listing["id"])).json()

    assert [run["id"] for run in listed] == [second["id"], first["id"]]


def test_demo_provider_output_is_marked_demo(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, DemoVisionProvider())
    listing = listing_with_photo(db, clients["agent"])
    clients["agent"].post(extractions(listing["id"]))

    run_jobs(db)

    [run] = clients["agent"].get(extractions(listing["id"])).json()
    assert (run["status"], run["provider"], run["is_demo"]) == ("succeeded", "demo", True)


def test_readers_can_list_but_not_request(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])

    # api_consumer has no listing:write; agent2 has it but does not own this listing.
    for role in ("api", "agent2"):
        response = clients[role].post(extractions(listing["id"]))
        assert response.status_code == 403, role
    assert clients["broker"].post(extractions(listing["id"])).status_code == 202
    for role in ("api", "agent2", "broker"):
        assert clients[role].get(extractions(listing["id"])).status_code == 200, role


def test_other_organisation_gets_not_found(
    db: Session,
    brokerage: Brokerage,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = listing_with_photo(db, clients["agent"])
    outsider = make_user("admin@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)

    assert other.post(extractions(listing["id"])).status_code == 404
    assert other.get(extractions(listing["id"])).status_code == 404


def test_listing_without_ready_photos_is_refused(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider())
    listing = new_listing(clients["agent"])
    upload(clients["agent"], listing["id"], image_bytes())  # still processing

    response = clients["agent"].post(extractions(listing["id"]))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_photos"
    assert db.scalar(select(AgentRun)) is None


def test_retryable_error_queues_the_job_again_and_last_attempt_fails_the_run(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider(*(ProviderUnavailable("503 high demand") for _ in range(3))))
    listing = listing_with_photo(db, clients["agent"])
    clients["agent"].post(extractions(listing["id"]))

    assert jobs.run_one(db) is True
    job = db.scalar(select(Job).where(Job.kind == "ai.extract"))
    assert job is not None and (job.status, job.attempts) == ("queued", 1)
    [run] = clients["agent"].get(extractions(listing["id"])).json()
    assert run["status"] == "queued"

    for _ in range(2):
        skip_backoff(db)
        assert jobs.run_one(db) is True

    db.refresh(job)
    assert job.status == "failed"
    [run] = clients["agent"].get(extractions(listing["id"])).json()
    assert run["status"] == "failed"
    assert "503 high demand" in run["error"]
    assert run["finished_at"]


def test_retry_after_a_transient_error_succeeds(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider(ProviderUnavailable("503")))
    listing = listing_with_photo(db, clients["agent"])
    clients["agent"].post(extractions(listing["id"]))

    jobs.run_one(db)
    skip_backoff(db)
    jobs.run_one(db)

    [run] = clients["agent"].get(extractions(listing["id"])).json()
    assert run["status"] == "succeeded"
    assert db.scalar(select(AgentRun.attempts)) == 2


def test_non_retryable_error_fails_the_run_at_once(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeProvider(ProviderRejected("API key not valid")))
    listing = listing_with_photo(db, clients["agent"])
    clients["agent"].post(extractions(listing["id"]))

    jobs.run_one(db)

    [run] = clients["agent"].get(extractions(listing["id"])).json()
    assert run["status"] == "failed"
    assert run["error"] == "ProviderRejected: API key not valid"
    job = db.scalar(select(Job).where(Job.kind == "ai.extract"))
    assert job is not None and job.status == "succeeded"  # nothing left to retry


def test_malformed_output_is_retried_once_then_fails(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    provider = use(monkeypatch, FakeProvider(MalformedOutput("bad"), MalformedOutput("bad again")))
    listing = listing_with_photo(db, clients["agent"])
    clients["agent"].post(extractions(listing["id"]))

    jobs.run_one(db)
    skip_backoff(db)
    jobs.run_one(db)

    [run] = clients["agent"].get(extractions(listing["id"])).json()
    assert run["status"] == "failed"
    assert run["error"] == "MalformedOutput: bad again"
    assert len(provider.calls) == 2
    assert jobs.run_one(db) is False
