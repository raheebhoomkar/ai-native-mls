"""Vision providers: one interface, a real adapter (Gemini, chunk 2) and a labelled demo one."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.ai.schemas import Extraction, Feature, PhotoExtraction, Region


@dataclass(frozen=True)
class Photo:
    media_asset_id: UUID
    content_type: str
    data: bytes


@dataclass(frozen=True)
class ProviderResult:
    extraction: Extraction
    provider: str
    model: str
    model_version: str | None = None


class ProviderError(Exception):
    """A provider call that did not give a usable answer. `retryable` says if trying later helps."""

    retryable = True


class ProviderUnavailable(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    pass


class RateLimited(ProviderError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MalformedOutput(ProviderError):
    pass


class ProviderRejected(ProviderError):
    """Bad key, bad request or blocked content: trying again will not help."""

    retryable = False


class VisionProvider(Protocol):
    def extract(self, photos: Sequence[Photo]) -> ProviderResult: ...


DEMO_PREFIX = "[Demo] "


class DemoVisionProvider:
    """Fixed output for when no model is configured. Every value says it is demo output."""

    def extract(self, photos: Sequence[Photo]) -> ProviderResult:
        note = "Demo output: no model looked at this photo."
        extraction = Extraction(
            photos=[
                PhotoExtraction(
                    media_asset_id=photo.media_asset_id,
                    features=[
                        Feature(
                            attribute="room_type",
                            value=f"{DEMO_PREFIX}living room",
                            confidence=0.5,
                            evidence=note,
                        ),
                        Feature(
                            attribute="flooring",
                            value=f"{DEMO_PREFIX}tiled floor",
                            confidence=0.4,
                            evidence=note,
                        ),
                    ],
                )
                for photo in photos
            ]
        )
        return ProviderResult(extraction=extraction, provider="demo", model="demo-fixed-v1")


# --- Region locators (redaction) -----------------------------------------------------------


@dataclass(frozen=True)
class LocatorResult:
    regions: list[Region]
    provider: str
    model: str
    model_version: str | None = None


class RegionLocator(Protocol):
    """Finds plates, phone numbers, watermarks and signage in one photo."""

    def locate(self, photo: Photo) -> LocatorResult: ...


class DemoRegionLocator:
    """No model configured: finds nothing. The run records the categories as not checked."""

    def locate(self, photo: Photo) -> LocatorResult:
        return LocatorResult(regions=[], provider="demo", model="none")
