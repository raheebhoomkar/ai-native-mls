from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ai.providers import DEMO_PREFIX, DemoVisionProvider, Photo
from app.modules.ai.schemas import Extraction


def _feature(**overrides: Any) -> dict[str, Any]:
    return {
        "attribute": "flooring",
        "value": "wooden floor",
        "confidence": 0.9,
        "evidence": "Plank pattern across the floor",
    } | overrides


def test_valid_output_parses_and_low_confidence_is_uncertain() -> None:
    photo_id = uuid4()
    extraction = Extraction.model_validate(
        {
            "photos": [
                {
                    "media_asset_id": str(photo_id),
                    "features": [_feature(), _feature(attribute="balcony", confidence=0.3)],
                }
            ]
        }
    )
    sure, unsure = extraction.photos[0].features
    assert not sure.uncertain
    assert unsure.uncertain
    extraction.check_inputs([photo_id])


@pytest.mark.parametrize(
    "feature",
    [
        _feature(attribute="bedroom_count"),  # not an observable attribute
        _feature(confidence=1.5),
        _feature(evidence=""),
        _feature(extra="field"),
    ],
)
def test_invalid_feature_is_rejected(feature: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(
            {"photos": [{"media_asset_id": str(uuid4()), "features": [feature]}]}
        )


def test_output_about_unsent_or_repeated_photos_is_rejected() -> None:
    sent, other = uuid4(), uuid4()
    unsent = Extraction.model_validate({"photos": [{"media_asset_id": str(other), "features": []}]})
    with pytest.raises(ValueError, match="not sent"):
        unsent.check_inputs([sent])
    twice = Extraction.model_validate(
        {"photos": [{"media_asset_id": str(sent), "features": []}] * 2}
    )
    with pytest.raises(ValueError, match="twice"):
        twice.check_inputs([sent])


def test_demo_provider_output_is_valid_and_labelled() -> None:
    photos = [Photo(uuid4(), "image/png", b"x") for _ in range(2)]
    result = DemoVisionProvider().extract(photos)
    assert result.provider == "demo"
    result.extraction.check_inputs([photo.media_asset_id for photo in photos])
    features = [f for p in result.extraction.photos for f in p.features]
    assert features and all(f.value.startswith(DEMO_PREFIX) and f.uncertain for f in features)
