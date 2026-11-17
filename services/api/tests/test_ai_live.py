"""Opt-in: calls the real Gemini API. Run with `pytest -m live`; needs GEMINI_API_KEY in .env."""

import io
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageFont

from app.core.config import REPO_ROOT, get_settings
from app.modules.ai.gemini import GeminiRegionLocator, GeminiVisionProvider
from app.modules.ai.providers import Photo

pytestmark = pytest.mark.live


def _room() -> bytes:
    """A drawn room: plank floor, window, sofa. No real property or person."""
    image = Image.new("RGB", (640, 480), (235, 230, 220))
    draw = ImageDraw.Draw(image)
    for x in range(0, 640, 40):
        draw.rectangle([x, 330, x + 38, 480], fill=(150, 100, 60))
    draw.rectangle([380, 60, 560, 250], fill=(170, 210, 240), outline=(255, 255, 255), width=8)
    draw.rectangle([60, 230, 300, 330], fill=(90, 90, 120))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _key() -> str:
    # conftest blanks the variable, so read the key from .env directly.
    key = dotenv_values(REPO_ROOT / ".env").get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY is not set in .env")
    return key


def test_gemini_extracts_features_from_a_photo() -> None:
    key = _key()
    settings = get_settings()
    photo = Photo(uuid4(), "image/png", _room())
    provider = GeminiVisionProvider(key, settings.gemini_model, settings.ai_timeout_seconds)
    result = provider.extract([photo])
    assert result.provider == "gemini"
    assert [p.media_asset_id for p in result.extraction.photos] == [photo.media_asset_id]
    assert result.extraction.photos[0].features


def test_gemini_locates_a_sign_with_a_phone_number() -> None:
    """A drawn yard sign with a made-up number; the note must not repeat the number."""
    key = _key()
    image = Image.new("RGB", (800, 600), (120, 160, 110))
    draw = ImageDraw.Draw(image)
    draw.rectangle([450, 300, 780, 480], fill=(240, 200, 30))
    font = ImageFont.load_default(size=40)
    draw.text((470, 320), "FOR SALE", fill=(0, 0, 0), font=font)
    draw.text((470, 390), "Call 98765 43210", fill=(0, 0, 0), font=font)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    settings = get_settings()
    locator = GeminiRegionLocator(key, settings.gemini_model, settings.ai_timeout_seconds)

    result = locator.locate(Photo(uuid4(), "image/jpeg", buffer.getvalue()))

    assert result.regions
    assert {r.category for r in result.regions} & {"phone_number", "signage"}
    assert all("98765" not in (r.note or "") for r in result.regions)
    # The sign is in the lower right; its box should be there too.
    assert any(r.box[0] + r.box[2] > 0.6 and r.box[1] > 0.4 for r in result.regions)
