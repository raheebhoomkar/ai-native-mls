"""Embedders: one interface, a Gemini adapter and a labelled demo one."""

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.config import get_settings
from app.modules.ai.gemini import GeminiClient
from app.modules.ai.providers import MalformedOutput

Purpose = Literal["document", "query"]


@dataclass(frozen=True)
class Embeddings:
    """Vectors for a batch of texts, in input order, with the model that made them."""

    vectors: list[list[float]]
    source: str
    model: str

    @property
    def dimension(self) -> int:
        return len(self.vectors[0]) if self.vectors else 0

    @property
    def model_key(self) -> str:
        """Vectors are only comparable with others of the same key."""
        return f"{self.source}/{self.model}/{self.dimension}"


class Embedder(Protocol):
    def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings: ...


_WORD = re.compile(r"\w+")
DEMO_DIMENSION = 256


def _demo_vector(text: str) -> list[float]:
    vector = [0.0] * DEMO_DIMENSION
    for word in _WORD.findall(text.lower()):
        padded = f" {word} "
        features = [(f"w:{word}", 1.0)]
        features += [(f"t:{padded[i : i + 3]}", 0.3) for i in range(len(padded) - 2)]
        for feature, weight in features:
            digest = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest())
            sign = 1.0 if digest >> 63 else -1.0
            vector[digest % DEMO_DIMENSION] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class DemoEmbedder:
    """Labelled demo: hashes words and spellings. It matches shared words, not meaning."""

    def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
        return Embeddings([_demo_vector(text) for text in texts], "demo", "hashing-v1")


EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
# Gemini accepts at most 100 texts per batch call.
BATCH_SIZE = 100
_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class GeminiEmbedder(GeminiClient):
    def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            request = {
                "requests": [
                    {
                        "model": f"models/{self._model}",
                        "content": {"parts": [{"text": text}]},
                        "taskType": _TASK_TYPES[purpose],
                    }
                    for text in batch
                ]
            }
            body = self._post(EMBED_URL.format(model=self._model), request)
            vectors += _read_vectors(body, len(batch))
        if len({len(vector) for vector in vectors}) > 1:
            raise MalformedOutput("Gemini returned vectors of different lengths.")
        return Embeddings(vectors, "gemini", self._model)


def _read_vectors(body: bytes, expected: int) -> list[list[float]]:
    try:
        vectors = [
            [float(value) for value in item["values"]] for item in json.loads(body)["embeddings"]
        ]
    except (ValueError, KeyError, TypeError) as error:
        raise MalformedOutput("Gemini embedding answer could not be read.") from error
    if len(vectors) != expected:
        raise MalformedOutput(f"Gemini returned {len(vectors)} vectors for {expected} texts.")
    if any(not vector or not all(map(math.isfinite, vector)) for vector in vectors):
        raise MalformedOutput("Gemini returned an empty or non-finite vector.")
    return vectors


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedder == "gemini" and settings.gemini_api_key is not None:
        return GeminiEmbedder(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_embedding_model,
            settings.ai_timeout_seconds,
        )
    return DemoEmbedder()
