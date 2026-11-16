"""Listing media (Module 3): upload validation, signed access, permissions, tenant isolation."""

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.media import service as media_service
from app.modules.media.storage import LocalStorage
from app.modules.organisations.models import Organisation
from tests.test_listings import LISTINGS, brokerage, new_listing, publish

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here

Brokerage = tuple[Organisation, dict[str, User], dict[str, TestClient]]

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64


@pytest.fixture(autouse=True)
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    local = LocalStorage(tmp_path)
    monkeypatch.setattr(media_service, "get_storage", lambda: local)
    return local


def upload(
    client: TestClient,
    listing_id: str,
    data: bytes = PNG,
    content_type: str = "image/png",
    filename: str = "front.png",
) -> Any:
    return client.post(
        f"{LISTINGS}/{listing_id}/media",
        params={"filename": filename},
        content=data,
        headers={"Content-Type": content_type},
    )


def test_agent_uploads_lists_and_downloads_media(
    db: Session, brokerage: Brokerage, client: TestClient, storage: LocalStorage
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])

    response = upload(clients["agent"], listing["id"], filename="C:\\photos\\front.png")
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["filename"] == "front.png"
    assert asset["content_type"] == "image/png"
    assert asset["size_bytes"] == len(PNG)
    assert asset["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert (asset["status"], asset["can_delete"]) == ("ready", True)

    listed = clients["broker"].get(f"{LISTINGS}/{listing['id']}/media").json()
    assert [item["id"] for item in listed] == [asset["id"]]

    # The signed link works with no session at all.
    content = client.get(asset["url"])
    assert content.status_code == 200
    assert content.content == PNG
    assert content.headers["content-type"] == "image/png"
    assert content.headers["x-content-type-options"] == "nosniff"

    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "media.uploaded"))
    assert event is not None and event.target_id == asset["id"]


@pytest.mark.parametrize(
    ("data", "content_type"),
    [(JPEG, "image/jpeg"), (JPEG, "image/jpg"), (WEBP, "image/webp")],
)
def test_other_image_types_are_accepted(
    brokerage: Brokerage, data: bytes, content_type: str
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    assert upload(clients["agent"], listing["id"], data, content_type).status_code == 201


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        (b"just text", "image/png"),  # declared image, is not one
        (JPEG, "image/png"),  # real image, declared as another type
        (PNG, "application/octet-stream"),
        (b"", "image/png"),
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", "image/webp"),
    ],
)
def test_invalid_files_are_rejected(brokerage: Brokerage, data: bytes, content_type: str) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])

    response = upload(clients["agent"], listing["id"], data, content_type)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert clients["agent"].get(f"{LISTINGS}/{listing['id']}/media").json() == []


def test_file_over_the_size_limit_is_rejected(
    brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    monkeypatch.setattr(get_settings(), "media_max_bytes", 2048)

    response = upload(clients["agent"], listing["id"], PNG + b"\x00" * 2048)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_only_who_may_edit_the_listing_may_upload_or_delete(brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    asset = upload(clients["agent"], listing["id"]).json()
    path = f"{LISTINGS}/{listing['id']}/media"

    # Another agent and a read-only API consumer can see the media but not change it.
    for role in ("agent2", "api"):
        assert clients[role].get(path).json()[0]["can_delete"] is False
        assert upload(clients[role], listing["id"]).status_code == 403
        assert clients[role].delete(f"/api/v1/media/{asset['id']}").status_code == 403

    # A broker manages every listing in the brokerage.
    assert upload(clients["broker"], listing["id"]).status_code == 201
    assert clients["broker"].delete(f"/api/v1/media/{asset['id']}").status_code == 204
    assert [item["id"] for item in clients["agent"].get(path).json()] != [asset["id"]]


def test_deleted_media_disappears_and_its_link_stops_working(
    db: Session, brokerage: Brokerage, client: TestClient
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    asset = upload(clients["agent"], listing["id"]).json()

    assert clients["agent"].delete(f"/api/v1/media/{asset['id']}").status_code == 204

    assert clients["agent"].get(f"{LISTINGS}/{listing['id']}/media").json() == []
    assert client.get(asset["url"]).status_code == 404
    assert clients["agent"].delete(f"/api/v1/media/{asset['id']}").status_code == 404
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "media.deleted")) is not None


def test_archived_listing_media_cannot_change(brokerage: Brokerage) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    asset = upload(clients["agent"], listing["id"]).json()
    assert clients["agent"].delete(f"{LISTINGS}/{listing['id']}").status_code == 204

    assert upload(clients["agent"], listing["id"]).status_code == 409
    assert clients["agent"].delete(f"/api/v1/media/{asset['id']}").status_code == 409


def test_other_organisation_cannot_reach_private_listing_media(
    brokerage: Brokerage,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    asset = upload(clients["agent"], listing["id"]).json()
    outsider = make_user("broker@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)

    assert other.get(f"{LISTINGS}/{listing['id']}/media").status_code == 404
    assert upload(other, listing["id"]).status_code == 404
    assert other.delete(f"/api/v1/media/{asset['id']}").status_code == 404


def test_network_listing_media_is_visible_but_read_only_to_other_organisations(
    brokerage: Brokerage,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    _, _, clients = brokerage
    listing = publish(clients["agent"], clients["broker"], visibility="network")
    upload(clients["agent"], listing["id"])
    outsider = make_user("broker@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)

    listed = other.get(f"{LISTINGS}/{listing['id']}/media").json()
    assert len(listed) == 1 and listed[0]["can_delete"] is False
    assert upload(other, listing["id"]).status_code == 403


def test_tampered_or_expired_links_are_refused(brokerage: Brokerage, client: TestClient) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    asset = upload(clients["agent"], listing["id"]).json()
    base = f"/api/v1/media/{asset['id']}/content"

    expired = int(time.time()) - 1
    for params in (
        {"expires": str(int(time.time()) + 60), "signature": "0" * 64},
        {
            "expires": str(expired),
            "signature": media_service._signature(UUID(asset["id"]), expired),
        },
    ):
        response = client.get(base, params=params)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "link_expired"


@pytest.mark.parametrize("key", ["../outside", "/etc/passwd", "", "a/../../b"])
def test_local_storage_refuses_keys_outside_its_root(storage: LocalStorage, key: str) -> None:
    with pytest.raises(ValueError, match="Invalid storage key"):
        storage.put(key, b"x", "image/png")


def test_production_requires_a_media_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("MEDIA_SIGNING_KEY", raising=False)
    with pytest.raises(ValueError, match="MEDIA_SIGNING_KEY"):
        Settings(_env_file=None)
