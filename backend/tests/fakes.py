"""
Test doubles.

FakeEmbeddingProvider stands in for OllamaEmbeddingProvider in tests, so
the RAG test suite doesn't require a live Ollama server. It uses a
deterministic feature-hashing scheme (hash each word into one of a fixed
number of buckets, sum, L2-normalize) rather than a real embedding model
— it has no semantic understanding, but text that shares more words
does score more similar, which is enough to test the actual things this
suite cares about: tenant filtering, top_k limiting, and relevance-
threshold cutoffs. Production always uses OllamaEmbeddingProvider; this
is confined to tests/.
"""

import hashlib

from app.providers.embedding.base import EmbeddingProvider

_DIMENSIONS = 32


class FakeEmbeddingProvider(EmbeddingProvider):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * _DIMENSIONS
        for word in text.lower().split():
            digest = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
            index = digest % _DIMENSIONS
            sign = 1.0 if (digest // _DIMENSIONS) % 2 == 0 else -1.0
            vector[index] += sign

        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    async def health_check(self) -> bool:
        return True
