"""Contract tests for the Gemini adapter against recorded responses (tests/fixtures/gemini).

`valid.json` is a real response captured on 2026-11-17; the others follow Gemini's error format.
"""

import json
import urllib.error
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import pytest

from app.modules.ai.gemini import GeminiVisionProvider
from app.modules.ai.providers import (
    DemoVisionProvider,
    MalformedOutput,
    Photo,
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
)
from app.modules.ai.service import get_provider

FIXTURES = Path(__file__).parent / "fixtures" / "gemini"
PHOTO = Photo(UUID("11111111-1111-4111-8111-111111111111"), "image/png", b"\x89PNG fake")


def _provider(
    status: int, fixture: str, headers: Mapping[str, str] | None = None
) -> tuple[GeminiVisionProvider, list[dict[str, object]]]:
    sent: list[dict[str, object]] = []

    def transport(
        url: str, request_headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        sent.append({"url": url, "headers": request_headers, "body": json.loads(body)})
        return status, headers or {}, (FIXTURES / fixture).read_bytes()

    return GeminiVisionProvider("test-key", "gemini-test", 30, transport), sent


def test_valid_response_is_parsed_with_model_version() -> None:
    provider, sent = _provider(200, "valid.json")
    result = provider.extract([PHOTO])
    assert (result.provider, result.model, result.model_version) == (
        "gemini",
        "gemini-test",
        "gemini-3.6-flash",
    )
    features = result.extraction.photos[0].features
    assert {f.attribute for f in features} == {"window", "flooring", "furnishing"}
    # The request: key in a header (never the URL), fixed system text, photo labelled by ID.
    request = sent[0]
    assert "test-key" not in str(request["url"])
    assert request["headers"]["x-goog-api-key"] == "test-key"  # type: ignore[index]
    body = request["body"]
    assert str(PHOTO.media_asset_id) in json.dumps(body["contents"])  # type: ignore[index]
    assert str(PHOTO.media_asset_id) not in json.dumps(body["systemInstruction"])  # type: ignore[index]


@pytest.mark.parametrize(
    "fixture", ["not_json.json", "schema_mismatch.json", "unsent_photo.json", "max_tokens.json"]
)
def test_unusable_output_is_malformed(fixture: str) -> None:
    provider, _ = _provider(200, fixture)
    with pytest.raises(MalformedOutput) as error:
        provider.extract([PHOTO])
    assert error.value.retryable


def test_rate_limit_carries_retry_delay() -> None:
    provider, _ = _provider(429, "rate_limited.json")
    with pytest.raises(RateLimited) as error:
        provider.extract([PHOTO])
    assert error.value.retry_after == 17
    provider, _ = _provider(429, "rate_limited.json", {"retry-after": "5"})
    with pytest.raises(RateLimited) as error:
        provider.extract([PHOTO])
    assert error.value.retry_after == 5


@pytest.mark.parametrize(
    ("status", "fixture", "expected", "retryable"),
    [
        (503, "unavailable.json", ProviderUnavailable, True),
        (404, "not_json.json", ProviderUnavailable, True),
        (400, "bad_key.json", ProviderRejected, False),
        (200, "blocked.json", ProviderRejected, False),
    ],
)
def test_http_failures_map_to_typed_errors(
    status: int, fixture: str, expected: type[ProviderError], retryable: bool
) -> None:
    provider, _ = _provider(status, fixture)
    with pytest.raises(expected) as error:
        provider.extract([PHOTO])
    assert error.value.retryable is retryable
    assert "test-key" not in str(error.value)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (TimeoutError("timed out"), ProviderTimeout),
        (urllib.error.URLError(TimeoutError("timed out")), ProviderTimeout),
        (urllib.error.URLError("Name or service not known"), ProviderUnavailable),
    ],
)
def test_network_failures(raised: Exception, expected: type[ProviderError]) -> None:
    def transport(*_: object) -> tuple[int, Mapping[str, str], bytes]:
        raise raised

    with pytest.raises(expected):
        GeminiVisionProvider("k", "m", 30, transport).extract([PHOTO])


def test_demo_adapter_without_key() -> None:
    # conftest blanks GEMINI_API_KEY, so the test run never reaches Gemini.
    assert isinstance(get_provider(), DemoVisionProvider)
