"""Embedding providers.

- ``OpenAIEmbedder``: text-embedding-3-small (1536 dims). Used when OPENAI_API_KEY is set.
- ``HashingEmbedder``: deterministic, offline, lexical (hashed words + bigrams). Used for tests
  and for running the demo without an API key. Not semantic — "car" and "vehicle" don't match —
  but good enough to check that permissions and ranking plumbing work.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request
from typing import Protocol, Sequence

EMBEDDING_DIM = 1536


_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i in is it its me my of on or our "
    "that the their them there these this to was we what when where which who why will with you your "
    "all any about into than then so not no".split()
)


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingError(RuntimeError):
    pass


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        words = [w for w in re.findall(r"\w+", text.lower()) if w not in _STOPWORDS]
        features = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        for feat in features:
            h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            vec[idx] += 1.0 if h[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]


class OpenAIEmbedder:
    name = "openai/text-embedding-3-small"

    def __init__(self, api_key: str | None = None, model: str = "text-embedding-3-small", batch_size: int = 100):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise EmbeddingError("OPENAI_API_KEY is not set")
        self.model = model
        self.batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._call(list(texts[i:i + self.batch_size])))
        return out

    def _call(self, batch: list[str]) -> list[list[float]]:
        req = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=json.dumps({"model": self.model, "input": batch}).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
        except Exception as exc:  # network, 429, 5xx — all retryable by the worker
            raise EmbeddingError(f"OpenAI embeddings call failed: {exc}") from exc
        data = sorted(payload["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


def default_embedder() -> Embedder:
    return OpenAIEmbedder() if os.environ.get("OPENAI_API_KEY") else HashingEmbedder()
