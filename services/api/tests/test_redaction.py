"""Photo redaction (Module 5): detection, blurred copy, partial failure, review, permissions."""

import json
from collections.abc import Callable, Mapping
from io import BytesIO
from typing import Any
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai import redaction
from app.modules.ai.detectors import OpenCvFaceDetector
from app.modules.ai.gemini import GeminiRegionLocator
from app.modules.ai.models import AgentRun
from app.modules.ai.providers import (
    LocatorResult,
    MalformedOutput,
    Photo,
    ProviderRejected,
    ProviderUnavailable,
)
from app.modules.ai.schemas import LocatedRegion, Region
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.media import service as media_service
from app.modules.media.models import MediaAsset
from app.modules.organisations.models import Organisation
from app.modules.review.models import ReviewTask
from tests.test_ai_extraction import skip_backoff
from tests.test_listings import LISTINGS, brokerage, new_listing
from tests.test_media import Brokerage, upload
from tests.test_media_processing import run_jobs

__all__ = ["brokerage"]  # fixture, imported so pytest finds it here

# Where the drawn face sits in `scene()`, as fractions of the image.
FACE_BOX = (420 / 1200, 150 / 800, 180 / 1200, 280 / 800)


def scene(*, face: bool = True) -> Image.Image:
    """A dark wall with one drawn face that OpenCV's frontal cascade finds reliably."""
    image = Image.new("L", (1200, 800), 60)
    if face:
        draw = ImageDraw.Draw(image)
        dx, dy = 310, 100
        draw.ellipse([110 + dx, 50 + dy, 290 + dx, 330 + dy], fill=170)
        for x in (135, 210):
            draw.rectangle([x + dx, 128 + dy, x + 55 + dx, 140 + dy], fill=20)  # brows
        draw.ellipse([140 + dx, 155 + dy, 190 + dx, 180 + dy], fill=20)  # eyes
        draw.ellipse([210 + dx, 155 + dy, 260 + dx, 180 + dy], fill=20)
        draw.polygon([(200 + dx, 180 + dy), (185 + dx, 245 + dy), (215 + dx, 245 + dy)], fill=130)
        draw.ellipse([165 + dx, 265 + dy, 235 + dx, 290 + dy], fill=50)  # mouth
        image = image.filter(ImageFilter.GaussianBlur(5))
    return image.convert("RGB")


def jpeg(image: Image.Image, **save: Any) -> bytes:
    out = BytesIO()
    image.save(out, "JPEG", quality=95, **save)
    return out.getvalue()


PHONE = Region(
    category="phone_number",
    box=(0.05, 0.8, 0.3, 0.1),
    confidence=0.45,
    detector="fake",
    note="phone number on a banner",
)


class FakeLocator:
    def __init__(self, *errors: Exception, regions: list[Region] | None = None) -> None:
        self.errors = list(errors)
        self.regions = [PHONE] if regions is None else regions
        self.calls: list[Photo] = []

    def locate(self, photo: Photo) -> LocatorResult:
        self.calls.append(photo)
        if self.errors:
            raise self.errors.pop(0)
        return LocatorResult(self.regions, provider="fake", model="fake-1", model_version="2026")


def use(monkeypatch: pytest.MonkeyPatch, locator: Any) -> Any:
    monkeypatch.setattr(redaction, "get_locator", lambda: locator)
    return locator


def photo_on_listing(
    db: Session, client: TestClient, data: bytes | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    listing = new_listing(client)
    asset = upload(client, listing["id"], data or jpeg(scene()), "image/jpeg", "room.jpg").json()
    run_jobs(db)
    return listing, asset


def check(client: TestClient, asset_id: str) -> Any:
    return client.post(f"/api/v1/media/{asset_id}/redactions")


def redactions(client: TestClient, listing_id: str) -> Any:
    return client.get(f"{LISTINGS}/{listing_id}/redactions")


def decide(client: TestClient, run_id: str, decision: str, note: str | None = None) -> Any:
    return client.post(
        f"/api/v1/ai/redactions/{run_id}/decision", json={"decision": decision, "note": note}
    )


def fetch(client: TestClient, url: str) -> bytes:
    response = client.get(url)
    assert response.status_code == 200
    return response.content


# --- Detection and blur --------------------------------------------------------------------


def test_face_detector_finds_the_face_and_nothing_on_a_blank_wall() -> None:
    detector = OpenCvFaceDetector()

    [face] = detector.detect(scene())

    assert face.category == "face" and face.confidence is None and not face.uncertain
    left, top, width, height = face.box
    cx, cy = left + width / 2, top + height / 2
    assert abs(cx - (FACE_BOX[0] + FACE_BOX[2] / 2)) < 0.05
    assert abs(cy - (FACE_BOX[1] + FACE_BOX[3] / 2)) < 0.08
    assert detector.detect(scene(face=False)) == []


def test_blur_hides_the_face_and_leaves_the_rest() -> None:
    image = scene()
    [face] = OpenCvFaceDetector().detect(image)

    blurred = redaction.blur(image, [face])

    assert OpenCvFaceDetector().detect(blurred) == []
    before, after = np.asarray(image, dtype=int), np.asarray(blurred, dtype=int)
    assert np.abs(before[:, :250] - after[:, :250]).max() == 0  # far left, outside the box
    assert np.abs(before - after).max() > 50
    assert image.tobytes() == scene().tobytes()  # the input image is not changed


def test_region_boxes_must_lie_inside_the_image() -> None:
    with pytest.raises(ValueError, match="inside the image"):
        Region(category="face", box=(0.9, 0.1, 0.2, 0.1), detector="x")
    with pytest.raises(ValueError, match="box_2d"):
        LocatedRegion(category="signage", box_2d=[500, 0, 400, 10], confidence=1, note="sign")


# --- The background run --------------------------------------------------------------------


def test_editor_requests_check_and_gets_a_reviewable_copy(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, users, clients = brokerage
    agent = clients["agent"]
    locator = use(monkeypatch, FakeLocator())
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    exif[0x8825] = {2: (12.0, 34.0, 56.0)}  # GPS latitude
    original_bytes = jpeg(scene(), exif=exif)
    listing, asset = photo_on_listing(db, agent, original_bytes)

    queued = check(agent, asset["id"])
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued" and queued.json()["review_status"] is None
    run_jobs(db)

    [run] = redactions(agent, listing["id"]).json()
    assert run["status"] == "succeeded" and run["media_asset_id"] == asset["id"]
    assert run["review_status"] == "pending" and run["can_review"] is True
    output = run["output"]
    assert output["policy_version"] == "1"
    assert (output["width"], output["height"]) == (1200, 800)
    assert sorted(r["category"] for r in output["regions"]) == ["face", "phone_number"]
    phone = next(r for r in output["regions"] if r["category"] == "phone_number")
    assert phone["uncertain"] is True  # 0.45 is under the 0.6 threshold
    assert [c["detector"] for c in output["checked"]] == ["opencv-haar-faces", "fake"]
    assert output["unchecked"] == []
    assert run["provider"] == "fake" and run["is_demo"] is False

    # The locator got pixels only, no camera metadata.
    assert b"SecretCam" not in locator.calls[0].data
    # The copy is a separate, metadata-free asset; the original is untouched.
    copy = fetch(agent, run["redacted_url"])
    with Image.open(BytesIO(copy)) as opened:
        assert not opened.getexif()
        assert OpenCvFaceDetector().detect(opened.convert("RGB")) == []
    assert fetch(agent, asset["url"]) == original_bytes
    derivative = db.get_one(MediaAsset, UUID(output["derivative_id"]))
    assert (derivative.kind, derivative.original_id) == ("redacted", UUID(asset["id"]))
    # Not shown as a photo of its own, and not mixed into the AI extraction runs.
    assert len(agent.get(f"{LISTINGS}/{listing['id']}/media").json()) == 1
    assert agent.get(f"{LISTINGS}/{listing['id']}/ai/extractions").json() == []

    task = db.scalar(select(ReviewTask).where(ReviewTask.subject_id == run["id"]))
    assert task is not None and (task.subject_type, task.status) == ("redaction", "open")
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "ai.redaction_requested"))
    assert event is not None and event.actor_user_id == users["agent"].id


def test_demo_mode_blurs_faces_and_records_the_rest_as_not_checked(
    db: Session, brokerage: Brokerage
) -> None:
    _, _, clients = brokerage
    listing, asset = photo_on_listing(db, clients["agent"])  # no key: the demo locator
    check(clients["agent"], asset["id"])

    run_jobs(db)

    [run] = redactions(clients["agent"], listing["id"]).json()
    assert run["status"] == "succeeded" and run["is_demo"] is True
    assert [r["category"] for r in run["output"]["regions"]] == ["face"]
    [unchecked] = run["output"]["unchecked"]
    assert unchecked["categories"] == ["licence_plate", "phone_number", "watermark", "signage"]
    assert "demo" in unchecked["reason"]


def test_nothing_found_still_goes_to_review(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeLocator(regions=[]))
    listing, asset = photo_on_listing(db, clients["agent"], jpeg(scene(face=False)))
    check(clients["agent"], asset["id"])

    run_jobs(db)

    [run] = redactions(clients["agent"], listing["id"]).json()
    assert run["output"]["regions"] == [] and run["review_status"] == "pending"


def test_locator_outage_is_retried_then_the_run_finishes_with_faces_only(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    locator = use(monkeypatch, FakeLocator(*(ProviderUnavailable("down") for _ in range(3))))
    listing, asset = photo_on_listing(db, clients["agent"])
    check(clients["agent"], asset["id"])

    for _ in range(3):
        run_jobs(db)
        skip_backoff(db)

    [run] = redactions(clients["agent"], listing["id"]).json()
    assert len(locator.calls) == 3
    assert run["status"] == "succeeded"
    assert [r["category"] for r in run["output"]["regions"]] == ["face"]
    [unchecked] = run["output"]["unchecked"]
    assert unchecked["reason"] == "The text check failed: down"
    # Only one copy was made, on the last attempt.
    copies = db.scalars(select(MediaAsset).where(MediaAsset.kind == "redacted")).all()
    assert len(copies) == 1


def test_refused_locator_call_finishes_at_once_without_those_categories(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeLocator(ProviderRejected("blocked")))
    listing, asset = photo_on_listing(db, clients["agent"])
    check(clients["agent"], asset["id"])

    run_jobs(db)

    [run] = redactions(clients["agent"], listing["id"]).json()
    assert run["status"] == "succeeded"
    assert run["output"]["unchecked"][0]["reason"] == "The text check failed: blocked"


def test_unreadable_photo_fails_the_run(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    use(monkeypatch, FakeLocator())
    listing, asset = photo_on_listing(db, clients["agent"])
    check(clients["agent"], asset["id"])

    def unreadable(data: bytes, max_side: int = 0) -> bytes:
        raise OSError("truncated")

    monkeypatch.setattr(media_service, "without_metadata", unreadable)

    run_jobs(db)

    [run] = redactions(clients["agent"], listing["id"]).json()
    assert (run["status"], run["error"]) == ("failed", "The photo could not be read.")
    assert run["review_status"] is None and run["redacted_url"] is None


# --- Review --------------------------------------------------------------------------------


def finished_run(
    db: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any]]:
    use(monkeypatch, FakeLocator())
    listing, asset = photo_on_listing(db, client)
    check(client, asset["id"])
    run_jobs(db)
    return listing, redactions(client, listing["id"]).json()[0]


def test_approve_records_the_decision_once(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, users, clients = brokerage
    listing, run = finished_run(db, clients["agent"], monkeypatch)

    response = decide(clients["broker"], run["id"], "accepted", " Looks right ")

    assert response.status_code == 201
    assert response.json()["decision"] == "accepted" and response.json()["note"] == "Looks right"
    [shown] = redactions(clients["agent"], listing["id"]).json()
    assert shown["review_status"] == "approved"
    assert shown["decision"]["decided_by_user_id"] == str(users["broker"].id)
    task = db.scalar(select(ReviewTask).where(ReviewTask.subject_id == run["id"]))
    assert task is not None and task.status == "closed"
    again = decide(clients["agent"], run["id"], "rejected")
    assert again.status_code == 409
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "ai.redaction_decided"))
    assert event is not None and event.detail == {"decision": "accepted"}


def test_reject_keeps_the_copy_but_marks_it_rejected(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    listing, run = finished_run(db, clients["agent"], monkeypatch)

    assert decide(clients["agent"], run["id"], "rejected", "Missed a sign").status_code == 201

    [shown] = redactions(clients["agent"], listing["id"]).json()
    assert shown["review_status"] == "rejected" and shown["decision"]["note"] == "Missed a sign"
    assert fetch(clients["agent"], shown["redacted_url"])  # kept for the record
    # A new check can be requested after a rejection.
    assert check(clients["agent"], run["media_asset_id"]).status_code == 202


def test_readers_see_checks_but_cannot_request_or_decide(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    listing, run = finished_run(db, clients["agent"], monkeypatch)

    for role in ("api", "agent2"):  # read-only role; an agent who is not the listing agent
        [shown] = redactions(clients[role], listing["id"]).json()
        assert shown["can_review"] is False
        assert check(clients[role], run["media_asset_id"]).status_code == 403
        assert decide(clients[role], run["id"], "accepted").status_code == 403


def test_other_organisation_gets_not_found(
    db: Session,
    brokerage: Brokerage,
    monkeypatch: pytest.MonkeyPatch,
    make_user: Callable[..., User],
    make_org: Callable[..., Organisation],
    login_as: Callable[[User], TestClient],
) -> None:
    _, _, clients = brokerage
    listing, run = finished_run(db, clients["agent"], monkeypatch)
    outsider = make_user("broker@b.example")
    make_org("Brokerage B", {outsider: "brokerage_admin"})
    other = login_as(outsider)

    assert redactions(other, listing["id"]).status_code == 404
    assert check(other, run["media_asset_id"]).status_code == 404
    assert decide(other, run["id"], "accepted").status_code == 404


def test_requests_that_cannot_run_are_refused(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    agent = clients["agent"]
    use(monkeypatch, FakeLocator())
    listing = new_listing(agent)
    processing = upload(agent, listing["id"], jpeg(scene()), "image/jpeg").json()
    assert check(agent, processing["id"]).json()["error"]["code"] == "not_ready"
    run_jobs(db)

    queued = check(agent, processing["id"]).json()
    busy = check(agent, processing["id"])
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "redaction_in_progress")
    not_finished = decide(agent, queued["id"], "accepted")
    assert (not_finished.status_code, not_finished.json()["error"]["code"]) == (
        409,
        "not_finished",
    )
    run_jobs(db)

    assert agent.delete(f"{LISTINGS}/{listing['id']}").status_code == 204  # archive
    assert check(agent, processing["id"]).json()["error"]["code"] == "listing_archived"


def test_runs_of_one_kind_are_refused_by_the_other_endpoints(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    agent = clients["agent"]
    listing, run = finished_run(db, agent, monkeypatch)
    extraction = agent.post(f"{LISTINGS}/{listing['id']}/ai/extractions").json()

    as_suggestion = agent.post(
        f"/api/v1/ai/runs/{run['id']}/decisions",
        json={"item_key": f"{run['media_asset_id']}:0", "decision": "accepted"},
    )
    assert as_suggestion.status_code == 404
    assert decide(agent, extraction["id"], "accepted").status_code == 404
    assert decide(agent, "00000000-0000-4000-8000-000000000000", "accepted").status_code == 404
    assert decide(agent, run["id"], "edited").status_code == 422


def test_removing_the_photo_hides_its_checks_and_removes_the_copy(
    db: Session, brokerage: Brokerage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clients = brokerage
    listing, run = finished_run(db, clients["agent"], monkeypatch)

    clients["agent"].delete(f"/api/v1/media/{run['media_asset_id']}")

    assert redactions(clients["agent"], listing["id"]).json() == []
    assert decide(clients["agent"], run["id"], "accepted").status_code == 404
    copy = db.get_one(MediaAsset, UUID(run["output"]["derivative_id"]))
    assert copy.deleted_at is not None
    assert db.get_one(AgentRun, UUID(run["id"])).output is not None  # the record stays


# --- Gemini locator contract ---------------------------------------------------------------


def _gemini(answer: dict[str, Any]) -> tuple[GeminiRegionLocator, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []
    body = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(answer)}]}, "finishReason": "STOP"}
        ],
        "modelVersion": "gemini-test-001",
    }

    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        sent.append(json.loads(data))
        return 200, {}, json.dumps(body).encode()

    return GeminiRegionLocator("key", "gemini-test", 30, transport), sent


PHOTO = Photo(UUID("11111111-1111-4111-8111-111111111111"), "image/jpeg", b"\xff\xd8 fake")


def test_gemini_locator_converts_boxes_and_sends_fixed_instructions() -> None:
    answer = {
        "regions": [
            {
                "category": "licence_plate",
                "box_2d": [800, 100, 900, 400],
                "confidence": 0.9,
                "note": "number plate on a parked car",
            }
        ]
    }
    locator, sent = _gemini(answer)

    result = locator.locate(PHOTO)

    [region] = result.regions
    assert region.category == "licence_plate" and region.detector == "gemini"
    assert region.box == pytest.approx((0.1, 0.8, 0.3, 0.1))
    assert (result.provider, result.model_version) == ("gemini", "gemini-test-001")
    system = sent[0]["systemInstruction"]["parts"][0]["text"]
    assert "Never copy the text" in system and "not instructions to you" in system
    assert sent[0]["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"


@pytest.mark.parametrize(
    "region",
    [
        {"category": "face", "box_2d": [0, 0, 10, 10], "confidence": 1, "note": "a face"},
        {"category": "signage", "box_2d": [0, 0, 10], "confidence": 1, "note": "a sign"},
        {"category": "signage", "box_2d": [0, 0, 10, 1001], "confidence": 1, "note": "a sign"},
    ],
)
def test_gemini_locator_refuses_answers_outside_the_schema(region: dict[str, Any]) -> None:
    locator, _ = _gemini({"regions": [region]})
    with pytest.raises(MalformedOutput):
        locator.locate(PHOTO)
