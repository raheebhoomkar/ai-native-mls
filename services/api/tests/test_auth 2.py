import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.audit.models import AuditEvent
from app.modules.auth import service
from app.modules.auth.models import AuthSession, User
from app.modules.auth.router import MAX_FAILURES_PER_EMAIL
from app.modules.organisations.models import Organisation
from tests.conftest import PASSWORD

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def _actions(db: Session) -> list[str]:
    return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)))


def test_login_sets_httponly_cookie_and_me_returns_memberships(
    client: TestClient,
    db: Session,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
) -> None:
    user = make_user("Agent@Example.com")
    org = make_org("Acme Realty", {user: "agent"})

    # Email matching ignores case and surrounding spaces.
    response = client.post(LOGIN, json={"email": " agent@example.COM ", "password": PASSWORD})

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie
    assert "password" not in response.text
    token = client.cookies["mls_session"]
    assert token not in response.text

    me = client.get(ME).json()
    assert me["user"]["email"] == "agent@example.com"
    assert me["memberships"] == [
        {
            "organisation_id": str(org.id),
            "organisation_name": "Acme Realty",
            "organisation_kind": "brokerage",
            "role": "agent",
        }
    ]

    stored = db.scalars(select(AuthSession)).one()
    assert stored.token_hash != token  # only a hash of the token is stored
    assert "auth.login" in _actions(db)


def test_wrong_password_and_unknown_email_get_the_same_answer(
    client: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    make_user("agent@example.com")

    wrong = client.post(LOGIN, json={"email": "agent@example.com", "password": "not the password"})
    unknown = client.post(LOGIN, json={"email": "nobody@example.com", "password": PASSWORD})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "set-cookie" not in wrong.headers
    # The failure is audited even though the request ended in an error.
    assert _actions(db) == ["auth.login_failed", "auth.login_failed"]


def test_inactive_user_cannot_sign_in_and_loses_existing_session(
    db: Session, make_user: Callable[..., User], login_as: Callable[[User], TestClient]
) -> None:
    user = make_user("agent@example.com")
    signed_in = login_as(user)

    user.is_active = False
    db.commit()

    assert signed_in.get(ME).status_code == 401
    again = signed_in.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    assert again.status_code == 401


def test_logout_revokes_the_session_server_side(
    app: FastAPI,
    make_user: Callable[..., User],
    login_as: Callable[[User], TestClient],
) -> None:
    signed_in = login_as(make_user("agent@example.com"))
    token = signed_in.cookies["mls_session"]

    assert signed_in.post("/api/v1/auth/logout").status_code == 204
    assert signed_in.get(ME).status_code == 401

    # A copy of the old cookie no longer works either.
    replay = TestClient(app)
    replay.cookies.set("mls_session", token)
    assert replay.get(ME).status_code == 401


def test_expired_session_is_rejected(
    db: Session, make_user: Callable[..., User], login_as: Callable[[User], TestClient]
) -> None:
    signed_in = login_as(make_user("agent@example.com"))

    db.scalars(select(AuthSession)).one().expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert signed_in.get(ME).status_code == 401


def test_requests_without_or_with_unknown_cookie_are_unauthenticated(client: TestClient) -> None:
    assert client.get(ME).status_code == 401
    client.cookies.set("mls_session", "made-up-token")
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_repeated_failures_lock_sign_in_for_that_email(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user("agent@example.com")

    for _ in range(MAX_FAILURES_PER_EMAIL):
        attempt = client.post(LOGIN, json={"email": "agent@example.com", "password": "wrong"})
        assert attempt.status_code == 401

    # Even the correct password is refused while the limit applies.
    locked = client.post(LOGIN, json={"email": "agent@example.com", "password": PASSWORD})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "rate_limited"


def test_login_rejects_malformed_body(client: TestClient) -> None:
    response = client.post(LOGIN, json={"email": "agent@example.com"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.password"


def test_create_user_enforces_password_length_and_unique_email(db: Session) -> None:
    with pytest.raises(AppError) as short:
        service.create_user(db, email="a@example.com", full_name="A", password="too short")
    assert short.value.status_code == 422

    service.create_user(db, email="a@example.com", full_name="A", password=PASSWORD)
    with pytest.raises(AppError) as duplicate:
        service.create_user(db, email=" A@EXAMPLE.com", full_name="A", password=PASSWORD)
    assert duplicate.value.code == "email_taken"


def test_cli_loads_every_model_outside_the_web_app() -> None:
    """Regression: the CLI failed on foreign keys to tables whose models it had not imported."""
    code = "import app.modules.auth.cli; from app.core.db import Base; Base.metadata.sorted_tables"
    result = subprocess.run(  # noqa: S603  # fixed arguments, no user input
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
