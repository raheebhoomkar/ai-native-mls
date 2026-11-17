"""Media processing (Module 3): thumbnails, failures and retry, retention, S3 storage."""

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.media.models import MediaAsset
from app.modules.media.storage import LocalStorage, S3Storage
from tests.test_listings import LISTINGS, brokerage, new_listing
from tests.test_media import Brokerage, upload

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (1200, 800), **save: Any) -> bytes:
    mode = "RGBA" if fmt == "PNG" else "RGB"
    out = BytesIO()
    Image.new(mode, size, (200, 40, 40, 128) if mode == "RGBA" else (200, 40, 40)).save(
        out, fmt, **save
    )
    return out.getvalue()


def run_jobs(db: Session) -> None:
    while jobs.run_one(db):
        pass


def media(client: TestClient, listing: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(f"{LISTINGS}/{listing['id']}/media").json()
    return result


def test_thumbnail_is_made_as_a_separate_asset_and_original_is_untouched(
    db: Session, brokerage: Brokerage, client: TestClient
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    exif = Image.Exif()
    exif[0x010F] = "Test Camera Co"  # Make
    original = image_bytes("JPEG", (2000, 1000), exif=exif)
    upload(clients["agent"], listing["id"], original, "image/jpeg")

    run_jobs(db)

    [item] = media(clients["agent"], listing)
    assert (item["status"], item["error"]) == ("ready", None)
    assert client.get(item["url"]).content == original
    thumb = client.get(item["thumbnail_url"])
    assert thumb.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(thumb.content)) as image:
        assert image.size == (480, 240)
        assert not image.getexif()  # camera metadata is not copied
    # A second run of the same job changes nothing.
    job = db.scalar(select(Job).where(Job.kind == "media.thumbnail"))
    assert job is not None
    jobs._handlers["media.thumbnail"](db, job)
    rows = db.scalars(select(MediaAsset).where(MediaAsset.listing_id == listing["id"])).all()
    assert sorted(row.kind for row in rows) == ["original", "thumbnail"]


def test_transparent_png_gets_a_white_background(
    db: Session, brokerage: Brokerage, client: TestClient
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    upload(clients["agent"], listing["id"], image_bytes("PNG"))
    run_jobs(db)

    [item] = media(clients["agent"], listing)
    with Image.open(BytesIO(client.get(item["thumbnail_url"]).content)) as image:
        red, green, _ = image.convert("RGB").getpixel((10, 10))  # type: ignore[misc]
        assert red > 200 and green > 100  # half-transparent red over white, not over black


def test_unreadable_image_fails_at_once_and_can_be_retried(
    db: Session, brokerage: Brokerage
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    asset = upload(clients["agent"], listing["id"]).json()  # PNG signature, no image after it

    run_jobs(db)

    [item] = media(clients["agent"], listing)
    assert item["status"] == "failed"
    assert item["error"] == "The image could not be read. Upload a different file."
    assert db.scalar(select(Job.attempts).where(Job.kind == "media.thumbnail")) == 1

    assert clients["agent2"].post(f"/api/v1/media/{asset['id']}/retry").status_code == 403
    retried = clients["agent"].post(f"/api/v1/media/{asset['id']}/retry")
    assert retried.status_code == 200
    assert (retried.json()["status"], retried.json()["error"]) == ("processing", None)
    again = clients["agent"].post(f"/api/v1/media/{asset['id']}/retry")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "not_failed"


def test_storage_outage_retries_then_shows_the_failure(
    db: Session, brokerage: Brokerage, storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    run_jobs(db)  # the property's geocoding job, so only the thumbnail job is left
    upload(clients["agent"], listing["id"], image_bytes())

    def unavailable(key: str) -> bytes:
        raise ConnectionError("storage unavailable")

    monkeypatch.setattr(storage, "get", unavailable)
    for _ in range(3):
        assert jobs.run_one(db) is True
        db.execute(update(Job).values(run_after=Job.created_at))  # skip the backoff
        assert media(clients["agent"], listing)[0]["status"] in ("processing", "failed")

    [item] = media(clients["agent"], listing)
    assert (item["status"], item["error"]) == ("failed", "Processing failed. Try again.")
    assert db.scalar(select(Job.status).where(Job.kind == "media.thumbnail")) == "failed"


def test_removed_media_files_are_deleted_after_the_retention_period(
    db: Session, brokerage: Brokerage, storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    listing = new_listing(clients["agent"])
    asset = upload(clients["agent"], listing["id"], image_bytes()).json()
    run_jobs(db)
    keys = db.scalars(select(MediaAsset.storage_key)).all()
    assert len(keys) == 2 and all((storage.root / key).exists() for key in keys)

    assert clients["agent"].delete(f"/api/v1/media/{asset['id']}").status_code == 204
    run_jobs(db)
    assert all((storage.root / key).exists() for key in keys)  # kept for 7 days

    db.execute(update(Job).values(run_after=Job.created_at))
    run_jobs(db)
    assert not any((storage.root / key).exists() for key in keys)
    assert db.scalar(select(Job.status).where(Job.kind == "media.purge")) == "succeeded"


class FakeS3:
    """The three calls S3Storage makes, with boto3's missing-key error."""

    class exceptions:  # noqa: N801  # mirrors boto3's client.exceptions
        class NoSuchKey(Exception):
            pass

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:  # noqa: N803
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey()
        return {"Body": BytesIO(self.objects[(Bucket, Key)][0])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop((Bucket, Key), None)


def test_s3_storage_behaves_like_local_storage(tmp_path: Path) -> None:
    for store in (LocalStorage(tmp_path), S3Storage("photos", FakeS3())):
        store.put("org/a", b"abc", "image/png")
        assert store.get("org/a") == b"abc"
        store.delete("org/a")
        store.delete("org/a")  # missing is fine
        with pytest.raises(FileNotFoundError):
            store.get("org/a")


def test_s3_storage_needs_a_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_STORAGE", "s3")
    monkeypatch.delenv("MEDIA_S3_BUCKET", raising=False)
    with pytest.raises(ValueError, match="MEDIA_S3_BUCKET"):
        Settings(_env_file=None)
    monkeypatch.setenv("MEDIA_S3_BUCKET", "photos")
    assert Settings(_env_file=None).media_s3_bucket == "photos"
    assert get_settings().media_storage == "local"
