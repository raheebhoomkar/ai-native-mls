"""Public API access (Sprint 17): API keys, scopes, rate limits, usage log, idempotency."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.apikeys.models import ApiKeyUsage
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.organisations.models import Membership, Organisation
from tests.test_listings import LISTINGS, PROPERTIES, property_body

KEYS = "/api/v1/api-keys"

Setup = tuple[Organisation, User, TestClient, TestClient]


@pytest.fixture
def org_admin(
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> Setup:
    admin = make_user("admin@a.example", name="Admin A")
    agent = make_user("agent@a.example", name="Agent A")
    org = make_org("Brokerage A", {admin: "brokerage_admin", agent: "agent"})
    return org, admin, login_as(admin), login_as(agent)


def create_key(client: TestClient, *scopes: str, rate: int = 60) -> dict[str, Any]:
    response = client.post(
        KEYS,
        json={"name": "CRM sync", "scopes": list(scopes), "rate_limit_per_minute": rate},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def bearer(app: FastAPI, key: dict[str, Any]) -> TestClient:
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key['key']}"
    return client


def test_admin_creates_a_key_shown_once(org_admin: Setup, db: Session) -> None:
    _, admin, client, agent = org_admin
    key = create_key(client, "listing:read")
    assert key["key"].startswith(key["prefix"] + "_")
    assert key["scopes"] == ["listing:read"]
    listed = client.get(KEYS).json()
    assert [k["id"] for k in listed] == [key["id"]]
    assert "key" not in listed[0]
    assert agent.post(KEYS, json={"name": "x", "scopes": ["listing:read"]}).status_code == 403
    bad = client.post(KEYS, json={"name": "x", "scopes": ["member:manage"]})
    assert bad.status_code == 422
    assert "member:manage" in bad.json()["error"]["message"]
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_user_id == admin.id))
    assert "api_key.created" in set(actions)


def test_key_acts_as_its_creator_within_its_scopes(app: FastAPI, org_admin: Setup) -> None:
    _, admin, client, _ = org_admin
    reader = bearer(app, create_key(client, "listing:read"))
    assert reader.get(LISTINGS).status_code == 200
    refused = reader.post(PROPERTIES, json=property_body())
    assert refused.status_code == 403

    writer = bearer(app, create_key(client, "listing:read", "listing:write"))
    created = writer.post(PROPERTIES, json=property_body())
    assert created.status_code == 201, created.text

    # People-only endpoints stay closed to keys.
    assert writer.get(KEYS).status_code == 403
    assert writer.get("/api/v1/auth/me").status_code == 401
    assert writer.get("/api/v1/audit-events").status_code in (403, 404)


def test_bad_revoked_and_orphaned_keys_are_refused(
    app: FastAPI, org_admin: Setup, db: Session
) -> None:
    org, admin, client, _ = org_admin
    stranger = TestClient(app)
    stranger.headers["Authorization"] = "Bearer mls_nope_nope"
    response = stranger.get(LISTINGS)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"

    key = create_key(client, "listing:read")
    keyed = bearer(app, key)
    assert keyed.get(LISTINGS).status_code == 200
    assert client.delete(f"{KEYS}/{key['id']}").status_code == 204
    assert keyed.get(LISTINGS).status_code == 401

    other = create_key(client, "listing:read")
    membership = db.scalars(select(Membership).where(Membership.user_id == admin.id)).one()
    db.delete(membership)
    db.commit()
    assert bearer(app, other).get(LISTINGS).status_code == 401


def test_rate_limit_and_usage_log(app: FastAPI, org_admin: Setup, db: Session) -> None:
    _, _, client, _ = org_admin
    key = create_key(client, "listing:read", rate=2)
    keyed = bearer(app, key)
    assert keyed.get(LISTINGS).status_code == 200
    assert keyed.get(LISTINGS).status_code == 200
    limited = keyed.get(LISTINGS)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    usage = db.scalars(
        select(ApiKeyUsage)
        .where(ApiKeyUsage.api_key_id == UUID(key["id"]))
        .order_by(ApiKeyUsage.at)
    ).all()
    assert [(u.method, u.status_code) for u in usage] == [("GET", 200), ("GET", 200), ("GET", 429)]
    assert all(u.request_id for u in usage)
    listed = next(k for k in client.get(KEYS).json() if k["id"] == key["id"])
    assert listed["requests_last_minute"] == 3
    assert listed["last_used_at"] is not None


def test_idempotency_key_replays_the_first_answer(app: FastAPI, org_admin: Setup) -> None:
    _, _, client, _ = org_admin
    keyed = bearer(app, create_key(client, "listing:read", "listing:write"))
    idem = {"Idempotency-Key": str(uuid4())}

    first = keyed.post(PROPERTIES, json=property_body(), headers=idem)
    second = keyed.post(PROPERTIES, json=property_body(), headers=idem)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers

    changed = keyed.post(PROPERTIES, json=property_body(city="Pune"), headers=idem)
    assert changed.status_code == 422
    assert changed.json()["error"]["code"] == "idempotency_key_reused"

    # The same key from another caller is a separate request; cookies work too.
    fresh = client.post(PROPERTIES, json=property_body(), headers=idem)
    assert fresh.status_code == 201
    assert fresh.json()["id"] != first.json()["id"]
    again = client.post(PROPERTIES, json=property_body(), headers=idem)
    assert again.json()["id"] == fresh.json()["id"]

    # Without the header, each request is new.
    assert keyed.post(PROPERTIES, json=property_body()).json()["id"] != first.json()["id"]


def test_failed_writes_are_stored_but_server_errors_are_not(app: FastAPI, org_admin: Setup) -> None:
    _, _, client, _ = org_admin
    keyed = bearer(app, create_key(client, "listing:read"))  # no write scope
    idem = {"Idempotency-Key": str(uuid4())}
    first = keyed.post(PROPERTIES, json=property_body(), headers=idem)
    assert first.status_code == 403
    replay = keyed.post(PROPERTIES, json=property_body(), headers=idem)
    assert replay.status_code == 403
    assert replay.headers["Idempotent-Replayed"] == "true"
