"""Opt-in: calls the real Gemini API. Run with `pytest -m live`; needs GEMINI_API_KEY in .env."""

import io
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from PIL import Image, ImageDraw

from app.core.config import REPO_ROOT, get_settings
from app.modules.ai.gemini import GeminiVisionProvider
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


def test_gemini_extracts_features_from_a_photo() -> None:
    # conftest blanks the variable, so read the key from .env directly.
    key = dotenv_values(REPO_ROOT / ".env").get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY is not set in .env")
    settings = get_settings()
    photo = Photo(uuid4(), "image/png", _room())
    provider = GeminiVisionProvider(key, settings.gemini_model, settings.ai_timeout_seconds)
    result = provider.extract([photo])
    assert result.provider == "gemini"
    assert [p.media_asset_id for p in result.extraction.photos] == [photo.media_asset_id]
    assert result.extraction.photos[0].features
