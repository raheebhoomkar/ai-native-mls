import json
import math
from collections.abc import Mapping

import pytest

from app.core.config import get_settings
from app.modules.ai.providers import MalformedOutput, RateLimited
from app.modules.search.embedder import (
    BATCH_SIZE,
    DemoEmbedder,
    GeminiEmbedder,
    get_embedder,
)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_demo_is_deterministic_normalised_and_labelled() -> None:
    first = DemoEmbedder().embed(["Sea-facing 2 BHK in Worli", ""], "document")
    again = DemoEmbedder().embed(["Sea-facing 2 BHK in Worli"], "query")
    assert first.vectors[0] == again.vectors[0]
    assert math.isclose(math.sqrt(cosine(first.vectors[0], first.vectors[0])), 1.0)
    assert first.vectors[1] == [0.0] * 256
    assert first.model_key == "demo/hashing-v1/256"


def test_demo_ranks_shared_words_higher() -> None:
    query, near, far = (
        DemoEmbedder()
        .embed(
            ["sea facing flat", "Sea-facing 3 BHK flat in Worli", "Office space near the IT park"],
            "document",
        )
        .vectors
    )
    assert cosine(query, near) > cosine(query, far)


Calls = list[tuple[str, dict[str, str], dict[str, object]]]


def fake(dimension: int = 4, status: int = 200, body: object = None, calls: Calls | None = None):  # type: ignore[no-untyped-def]
    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        request = json.loads(data)
        if calls is not None:
            calls.append((url, headers, request))
        answer = body or {
            "embeddings": [{"values": [0.5] * dimension} for _ in request["requests"]]
        }
        return status, {}, json.dumps(answer).encode()

    return transport


def test_gemini_request_batches_and_reads_dimension() -> None:
    calls: Calls = []
    embedder = GeminiEmbedder("key", "gemini-embedding-001", 5, transport=fake(7, calls=calls))
    result = embedder.embed([f"text {i}" for i in range(BATCH_SIZE + 1)], "query")
    assert len(result.vectors) == BATCH_SIZE + 1
    assert result.model_key == "gemini/gemini-embedding-001/7"
    assert [len(request["requests"]) for _, _, request in calls] == [BATCH_SIZE, 1]  # type: ignore[arg-type]
    url, headers, request = calls[0]
    assert url.startswith("https://") and url.endswith(
        "/models/gemini-embedding-001:batchEmbedContents"
    )
    assert headers["x-goog-api-key"] == "key"
    first = request["requests"][0]  # type: ignore[index]
    assert first["model"] == "models/gemini-embedding-001"
    assert first["taskType"] == "RETRIEVAL_QUERY"
    assert first["content"] == {"parts": [{"text": "text 0"}]}


@pytest.mark.parametrize(
    "body",
    [
        {"embeddings": [{"values": [0.1, 0.2]}]},  # one vector for two texts
        {"embeddings": [{"values": [0.1]}, {"values": [0.1, 0.2]}]},  # mixed lengths
        {"embeddings": [{"values": []}, {"values": []}]},
        {"embeddings": [{"values": ["x"]}, {"values": [1]}]},
        {"nothing": True},
    ],
)
def test_gemini_bad_answers_are_malformed(body: object) -> None:
    embedder = GeminiEmbedder("key", "m", 5, transport=fake(body=body))
    with pytest.raises(MalformedOutput):
        embedder.embed(["a", "b"], "document")


def test_gemini_rate_limit_is_mapped() -> None:
    embedder = GeminiEmbedder("key", "m", 5, transport=fake(status=429, body={"error": {}}))
    with pytest.raises(RateLimited):
        embedder.embed(["a"], "document")


def test_get_embedder_needs_explicit_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        monkeypatch.setenv("GEMINI_API_KEY", "key")
        get_settings.cache_clear()
        assert isinstance(get_embedder(), DemoEmbedder)
        monkeypatch.setenv("EMBEDDER", "gemini")
        get_settings.cache_clear()
        assert isinstance(get_embedder(), GeminiEmbedder)
        monkeypatch.setenv("GEMINI_API_KEY", "")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="EMBEDDER is gemini"):
            get_settings()
    finally:
        get_settings.cache_clear()
