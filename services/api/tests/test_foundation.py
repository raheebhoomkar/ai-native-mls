import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.logging import JsonFormatter, request_id_var
from app.core.pagination import Page, PageParamsDep, decode_cursor, encode_cursor
from app.main import create_app


def test_health_reports_database_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response.headers["X-Request-ID"]


def test_health_returns_503_envelope_when_database_is_down() -> None:
    class BrokenSession:
        def execute(self, *_: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def broken_session() -> Iterator[Session]:
        yield BrokenSession()  # type: ignore[misc]

    app = create_app()
    app.dependency_overrides[get_session] = broken_session
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "database_unavailable"
    assert "connection refused" not in response.text
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_safe_request_id_is_echoed_and_unsafe_one_is_replaced(client: TestClient) -> None:
    echoed = client.get("/api/v1/health", headers={"X-Request-ID": "client-id-12345"})
    assert echoed.headers["X-Request-ID"] == "client-id-12345"
    replaced = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert replaced.headers["X-Request-ID"] != "bad id\twith spaces"


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]


def _probe_app() -> FastAPI:
    """The real app plus throwaway routes that exercise shared behaviour."""
    app = create_app()

    class Item(BaseModel):
        n: int

    @app.get("/probe/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/probe/app-error")
    def app_error() -> None:
        raise AppError(409, "conflict", "Already exists.")

    @app.get("/probe/items")
    def items(page: PageParamsDep) -> Page[Item]:
        start = page.cursor["n"] if page.cursor else 0
        end = start + page.limit
        return Page(
            items=[Item(n=n) for n in range(start, min(end, 5))],
            next_cursor=encode_cursor({"n": end}) if end < 5 else None,
        )

    return app


def test_unhandled_error_is_logged_but_not_leaked() -> None:
    response = TestClient(_probe_app()).get("/probe/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.text
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_app_error_maps_to_envelope() -> None:
    response = TestClient(_probe_app()).get("/probe/app-error")
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Already exists."


def test_pagination_walks_pages_and_rejects_bad_input() -> None:
    client = TestClient(_probe_app())

    first = client.get("/probe/items", params={"limit": 3}).json()
    assert [item["n"] for item in first["items"]] == [0, 1, 2]
    second = client.get("/probe/items", params={"limit": 3, "cursor": first["next_cursor"]}).json()
    assert [item["n"] for item in second["items"]] == [3, 4]
    assert second["next_cursor"] is None

    too_big = client.get("/probe/items", params={"limit": 1000})
    assert too_big.status_code == 422
    assert too_big.json()["error"]["details"][0]["field"] == "query.limit"

    bad_cursor = client.get("/probe/items", params={"cursor": "!!not-a-cursor!!"})
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error"]["code"] == "invalid_cursor"


def test_cursor_round_trip_and_non_object_rejected() -> None:
    assert decode_cursor(encode_cursor({"id": "abc", "n": 7})) == {"id": "abc", "n": 7}
    with pytest.raises(AppError):
        decode_cursor(encode_cursor([1, 2]))  # type: ignore[arg-type]


def test_settings_reject_missing_or_malformed_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    monkeypatch.setenv("DATABASE_URL", "not-a-url")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_log_lines_are_json_with_request_id() -> None:
    token = request_id_var.set("req-123")
    try:
        record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
        record.status = 200
        entry = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert entry["message"] == "hello"
    assert entry["request_id"] == "req-123"
    assert entry["status"] == 200


@pytest.mark.parametrize(
    "url",
    ["postgres://u:p@db.example:5432/mls", "postgresql://u:p@db.example:5432/mls"],
)
def test_host_style_database_urls_are_given_the_psycopg_driver(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    assert str(Settings(_env_file=None).database_url) == (
        "postgresql+psycopg://u:p@db.example:5432/mls"
    )


def test_api_serves_the_built_web_app_without_shadowing_the_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>MLS web</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert "MLS web" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/v1/health").json() == {"status": "ok", "database": "ok"}
        # Unknown API paths still get the JSON error envelope, not the web page.
        missing = client.get("/api/v1/nope")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
        assert client.get("/../etc/passwd").status_code == 404
    finally:
        get_settings.cache_clear()


def test_seed_in_production_needs_explicit_settings_and_uses_their_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app import seed as seed_module

    def configure(**env: str) -> None:
        for name in ("SEED_DEMO_DATA", "SEED_PASSWORD"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    seeded: list[str] = []

    def fake_seed(session: Session, password: str) -> list[str]:
        seeded.append(password)
        return ["user demo"]

    monkeypatch.setattr(seed_module, "seed", fake_seed)
    try:
        configure()
        assert seed_module.main(["--if-configured"]) == 0  # silent no-op at container start
        assert seed_module.main([]) == 1
        configure(SEED_DEMO_DATA="true")
        assert seed_module.main([]) == 1  # no password: never fall back to the published one
        assert seeded == []

        configure(SEED_DEMO_DATA="true", SEED_PASSWORD="a-generated-secret-value")
        assert seed_module.main(["--if-configured"]) == 0
        assert seeded == ["a-generated-secret-value"]
        output = capsys.readouterr().out
        assert "a-generated-secret-value" not in output
        assert seed_module.SEED_PASSWORD not in output
    finally:
        get_settings.cache_clear()
