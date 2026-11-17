"""Hardening (Sprint 21): ops status and alerts, cleanup, dead-letter list for webhooks."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.apikeys.models import ApiKeyUsage, IdempotencyRecord
from app.modules.auth.models import User
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.ops import service as ops
from app.modules.organisations.models import Organisation
from app.modules.webhooks.models import WebhookDelivery, WebhookSubscription

STATUS = "/api/v1/ops/status"
FAILED = "/api/v1/webhooks/deliveries/failed"


def _ago(**kwargs: float) -> datetime:
    return datetime.now(UTC) - timedelta(**kwargs)


def test_ops_status_is_for_platform_admins_and_names_problems(
    db: Session,
    client: TestClient,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    platform = login_as(make_user("ops@platform.example", platform_admin=True))
    org_admin = make_user("admin@a.example")
    make_org("Brokerage A", {org_admin: "brokerage_admin"})

    assert login_as(org_admin).get(STATUS).status_code == 403
    assert client.get(STATUS).status_code == 401

    jobs.enqueue(db, "retired.kind", delay=timedelta(minutes=-10))
    db.commit()
    body = platform.get(STATUS).json()
    assert "retired.kind" in body["jobs"]["unknown_kinds"]
    assert body["jobs"]["overdue"] >= 1
    assert any("retired.kind" in alert for alert in body["alerts"])
    assert any("worker is running" in alert for alert in body["alerts"])


def test_unknown_job_kind_fails_at_once_with_an_alert(
    db: Session, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Alembic's logging config, run once for the test database, disables existing loggers.
    monkeypatch.setattr(jobs.logger, "disabled", False)
    db.execute(delete(Job).where(Job.status.in_(("queued", "running"))))
    job = jobs.enqueue(db, "retired.kind", max_attempts=3)
    db.commit()

    with caplog.at_level(logging.ERROR):
        assert jobs.run_one(db) is True
    db.refresh(job)
    assert (job.status, job.attempts) == ("failed", 1)
    alerts = {getattr(r, "alert", None) for r in caplog.records}
    assert {"unknown_job_kind", "job_failed"} <= alerts


def test_cleanup_removes_expired_rows_and_keeps_dead_letters(db: Session) -> None:
    key_id, org_id = uuid4(), uuid4()
    usage_old = ApiKeyUsage(
        api_key_id=key_id,
        organisation_id=org_id,
        at=_ago(days=91),
        method="GET",
        path="/x",
        status_code=200,
    )
    usage_new = ApiKeyUsage(
        api_key_id=key_id,
        organisation_id=org_id,
        at=_ago(days=1),
        method="GET",
        path="/x",
        status_code=200,
    )
    record_old = IdempotencyRecord(
        principal="p",
        key="old",
        method="POST",
        path="/x",
        request_hash="h",
        created_at=_ago(hours=25),
    )
    record_new = IdempotencyRecord(
        principal="p", key="new", method="POST", path="/x", request_hash="h"
    )
    done_old = Job(kind="test.x", status="succeeded", finished_at=_ago(days=31))
    done_new = Job(kind="test.x", status="succeeded", finished_at=_ago(days=1))
    failed_old = Job(kind="test.x", status="failed", finished_at=_ago(days=60))
    expired: list[Any] = [usage_old, record_old, done_old]
    kept: list[Any] = [usage_new, record_new, done_new, failed_old]
    db.add_all(expired + kept)
    db.commit()
    expired_ids = [(type(r), r.id) for r in expired]
    kept_ids = [(type(r), r.id) for r in kept]

    ops.cleanup(db, Job(kind=ops.CLEANUP_KIND))
    db.commit()

    def exists(model: Any, row_id: UUID) -> bool:
        return db.execute(select(model.id).where(model.id == row_id)).first() is not None

    assert [exists(m, i) for m, i in expired_ids] == [False] * 3
    assert [exists(m, i) for m, i in kept_ids] == [True] * 4


def test_cleanup_is_queued_once_a_day(db: Session) -> None:
    db.execute(delete(Job).where(Job.kind == ops.CLEANUP_KIND))
    db.commit()

    first = ops.ensure_cleanup_scheduled(db)
    assert first is not None and first.kind == ops.CLEANUP_KIND
    assert ops.ensure_cleanup_scheduled(db) is None

    first.status, first.created_at = "succeeded", _ago(hours=25)
    db.commit()
    assert ops.ensure_cleanup_scheduled(db) is not None


def test_failed_deliveries_list_is_per_organisation(
    db: Session,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    admin_a, admin_b = make_user("admin@a.example"), make_user("admin@b.example")
    agent_a = make_user("agent@a.example")
    org_a = make_org("Brokerage A", {admin_a: "brokerage_admin", agent_a: "agent"})
    org_b = make_org("Brokerage B", {admin_b: "brokerage_admin"})

    def delivery(org: Organisation, admin: User, status: str) -> WebhookDelivery:
        hook = WebhookSubscription(
            organisation_id=org.id,
            created_by_user_id=admin.id,
            url="https://x.example/h",
            event_kinds=["listing.changed"],
            secret="s",
        )
        db.add(hook)
        db.flush()
        row = WebhookDelivery(
            subscription_id=hook.id,
            event_kind="ping",
            body="{}",
            status=status,
            attempts=6,
            created_at=datetime.now(UTC),
        )
        db.add(row)
        return row

    failed_a = delivery(org_a, admin_a, "failed")
    delivery(org_a, admin_a, "succeeded")
    delivery(org_b, admin_b, "failed")
    db.commit()

    response = login_as(admin_a).get(FAILED)
    assert response.status_code == 200
    assert [d["id"] for d in response.json()] == [str(failed_a.id)]
    assert login_as(agent_a).get(FAILED).status_code == 403


RUN_JOBS = "/api/v1/ops/run-jobs"
ticked: list[str] = []


@jobs.handler("test.ops_tick")
def _tick(session: Session, job: Job) -> None:
    ticked.append(job.payload["name"])


def test_run_jobs_needs_the_cron_secret_and_runs_due_jobs(
    db: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticked.clear()
    assert client.get(RUN_JOBS).status_code == 404  # no CRON_SECRET: the route is off

    monkeypatch.setattr(get_settings(), "cron_secret", SecretStr("s" * 32))
    assert client.get(RUN_JOBS).status_code == 401
    wrong = client.get(RUN_JOBS, headers={"Authorization": "Bearer " + "x" * 32})
    assert wrong.status_code == 401

    job = jobs.enqueue(db, "test.ops_tick", payload={"name": "due"})
    db.commit()
    response = client.get(RUN_JOBS, headers={"Authorization": "Bearer " + "s" * 32})
    assert response.status_code == 200
    assert response.json()["ran"] >= 1
    assert ticked == ["due"]
    db.refresh(job)
    assert job.status == "succeeded"
    assert jobs.exists_since(db, ops.CLEANUP_KIND, _ago(minutes=1))  # cleanup queued too
