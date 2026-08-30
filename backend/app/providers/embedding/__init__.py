"""Embedding Provider Package"""

from typing import Optional

from app.providers.embedding.base import EmbeddingProvider
from app.providers.embedding.ollama_provider import OllamaEmbeddingProvider

__all__ = ["EmbeddingProvider", "OllamaEmbeddingProvider", "get_embedding_provider"]

_embedding_provider: Optional[EmbeddingProvider] = None


async def get_embedding_provider() -> EmbeddingProvider:
    """Get the (lazily-initialized, process-wide) embedding provider.

    A FastAPI dependency — override with `app.dependency_overrides` in
    tests to avoid requiring a live Ollama server.
    """
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = OllamaEmbeddingProvider()
    return _embedding_provider
