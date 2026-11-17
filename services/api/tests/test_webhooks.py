"""Webhooks (Sprint 18): subscriptions, signed deliveries from the outbox, retries, log."""

import json
import socket
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.jobs.models import Job
from app.modules.organisations.models import Organisation
from app.modules.webhooks import service
from tests.test_api_keys import Setup, bearer, create_key, org_admin
from tests.test_listings import LISTINGS, new_listing
from tests.test_media_processing import run_jobs

__all__ = ["org_admin"]  # fixture, imported so pytest finds it here

HOOKS = "/api/v1/webhooks"
URL = "https://crm.example.com/hooks/mls"


class FakeSender:
    """Records each request; answers with the queued statuses, then 200."""

    def __init__(self, *statuses: int | Exception) -> None:
        self.statuses = list(statuses)
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(
        self, url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> tuple[int, str]:
        self.calls.append((url, body, headers))
        status = self.statuses.pop(0) if self.statuses else 200
        if isinstance(status, Exception):
            raise status
        return status, "ok" if status < 300 else "server error"


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> FakeSender:
    fake = FakeSender()
    monkeypatch.setattr(service, "get_sender", lambda: fake)
    return fake


def subscribe(client: TestClient, *events: str, url: str = URL) -> dict[str, Any]:
    response = client.post(HOOKS, json={"url": url, "event_kinds": list(events)})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def deliveries(client: TestClient, hook: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(f"{HOOKS}/{hook['id']}/deliveries").json()
    return result


def drain(db: Session) -> None:
    """Run every job, including retries queued for later."""
    for _ in range(service.MAX_ATTEMPTS + 2):
        run_jobs(db)
        db.execute(update(Job).where(Job.status == "queued").values(run_after=Job.created_at))
        db.commit()


def test_listing_change_is_delivered_signed(
    db: Session, org_admin: Setup, sender: FakeSender
) -> None:
    _, _, admin, agent = org_admin
    hook = subscribe(admin, "listing.changed")
    assert hook["secret"].startswith("whsec_")
    assert "secret" not in admin.get(HOOKS).json()[0]

    listing = new_listing(agent)
    drain(db)

    assert len(sender.calls) == 1
    url, body, headers = sender.calls[0]
    assert url == URL
    assert headers["X-MLS-Event"] == "listing.changed"
    assert service.verify(hook["secret"], headers["X-MLS-Signature"], body)
    event = json.loads(body)
    assert event["type"] == "listing.changed"
    assert event["data"] == {"subject_type": "listing", "subject_id": listing["id"]}

    [delivery] = deliveries(admin, hook)
    assert delivery["status"] == "succeeded"
    assert delivery["attempts"] == 1
    assert delivery["last_status_code"] == 200


def test_only_subscribed_events_are_sent(db: Session, org_admin: Setup, sender: FakeSender) -> None:
    _, _, admin, agent = org_admin
    hook = subscribe(admin, "workflow.finished")
    listing = new_listing(agent)
    drain(db)
    assert sender.calls == []

    assert agent.post(f"{LISTINGS}/{listing['id']}/workflows").status_code == 202
    drain(db)
    kinds = [headers["X-MLS-Event"] for _, _, headers in sender.calls]
    assert kinds == ["workflow.finished"]
    data = json.loads(sender.calls[0][1])["data"]
    assert data["status"] == "succeeded"
    assert deliveries(admin, hook)[0]["event_kind"] == "workflow.finished"


def test_failed_endpoint_is_retried_with_backoff_then_redelivered(
    db: Session, org_admin: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, admin, agent = org_admin
    fake = FakeSender(*[500] * service.MAX_ATTEMPTS)
    monkeypatch.setattr(service, "get_sender", lambda: fake)
    hook = subscribe(admin, "listing.changed")
    new_listing(agent)

    run_jobs(db)  # fan-out and the first attempt; the second waits 30 s
    [delivery] = deliveries(admin, hook)
    assert (delivery["status"], delivery["attempts"]) == ("pending", 1)
    assert delivery["last_error"] == "The endpoint answered HTTP 500."
    assert delivery["next_attempt_at"] is not None

    drain(db)
    [delivery] = deliveries(admin, hook)
    assert (delivery["status"], delivery["attempts"]) == ("failed", service.MAX_ATTEMPTS)
    assert len(fake.calls) == service.MAX_ATTEMPTS

    again = admin.post(f"{HOOKS}/deliveries/{delivery['id']}/redeliver")
    assert again.status_code == 202
    assert again.json()["status"] == "pending"
    drain(db)
    [delivery] = deliveries(admin, hook)
    assert delivery["status"] == "succeeded"
    assert len({body for _, body, _ in fake.calls}) == 1  # same body every time


def test_network_error_counts_as_a_failed_attempt(
    db: Session, org_admin: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, admin, _ = org_admin
    fake = FakeSender(TimeoutError("timed out"))
    monkeypatch.setattr(service, "get_sender", lambda: fake)
    hook = subscribe(admin, "listing.changed")
    assert admin.post(f"{HOOKS}/{hook['id']}/test").status_code == 202
    run_jobs(db)
    [delivery] = deliveries(admin, hook)
    assert delivery["event_kind"] == "ping"
    assert "timed out" in delivery["last_error"]
    drain(db)
    assert deliveries(admin, hook)[0]["status"] == "succeeded"


def test_disabled_webhook_gets_nothing(db: Session, org_admin: Setup, sender: FakeSender) -> None:
    _, _, admin, agent = org_admin
    hook = subscribe(admin, "listing.changed")
    assert admin.post(f"{HOOKS}/{hook['id']}/test").status_code == 202  # pending delivery
    new_listing(agent)  # its event is fanned out after the hook is off
    assert admin.delete(f"{HOOKS}/{hook['id']}").status_code == 204
    drain(db)

    assert sender.calls == []
    [delivery] = deliveries(admin, hook)
    assert (delivery["event_kind"], delivery["status"]) == ("ping", "failed")
    assert delivery["last_error"] == "The webhook was turned off."
    assert admin.post(f"{HOOKS}/{hook['id']}/test").status_code == 409


def test_only_people_who_administer_manage_webhooks(
    app: FastAPI,
    org_admin: Setup,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    _, _, admin, agent = org_admin
    hook = subscribe(admin, "listing.changed")
    assert agent.get(HOOKS).status_code == 403
    keyed = bearer(app, create_key(admin, "listing:read", "listing:write"))
    assert keyed.get(HOOKS).status_code == 403

    outsider = make_user("admin@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)
    assert other.get(f"{HOOKS}/{hook['id']}/deliveries").status_code == 404
    assert other.delete(f"{HOOKS}/{hook['id']}").status_code == 404
    assert other.get(HOOKS).json() == []

    bad = admin.post(HOOKS, json={"url": URL, "event_kinds": ["listing.deleted"]})
    assert bad.status_code == 422
    ftp = admin.post(HOOKS, json={"url": "ftp://example.com/x", "event_kinds": ["listing.changed"]})
    assert ftp.json()["error"]["code"] == "webhook_url_not_allowed"


def test_production_refuses_plain_http_and_private_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(environment="production"))
    for url in ("http://example.com/hook", "https://127.0.0.1/hook", "https://localhost/hook"):
        with pytest.raises(AppError) as refused:
            service.check_url(url)
        assert refused.value.code == "webhook_url_not_allowed", url
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *_: [(None, None, None, "", ("93.184.215.14", 443))]
    )
    service.check_url("https://example.com/hook")  # a public address is fine


def test_signature_check_refuses_tampering_and_old_messages() -> None:
    body = b'{"type":"ping"}'
    now = int(time.time())
    header = service.sign("whsec_x", now, body)
    assert service.verify("whsec_x", header, body)
    assert not service.verify("whsec_y", header, body)
    assert not service.verify("whsec_x", header, body + b" ")
    old = service.sign("whsec_x", now - service.TOLERANCE_SECONDS - 1, body)
    assert not service.verify("whsec_x", old, body)
    assert not service.verify("whsec_x", "garbage", body)
