"""
Base Embedding Provider

Abstract interface for text-embedding providers, used by the RAG pipeline
to turn restaurant knowledge (and caller questions) into vectors. Kept
separate from LLMProvider even though Ollama serves both, since a future
deployment might reasonably swap one without the other (e.g. a larger
remote LLM with a small local embedding model for latency).
"""

from abc import ABC, abstractmethod
from typing import List


class EmbeddingProvider(ABC):
    """Abstract base class for text-embedding providers."""

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a batch of texts.

        Args:
            texts: Texts to embed. Order is preserved in the result.

        Returns:
            One embedding vector (list of floats) per input text, in the
            same order.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy and accessible."""
        pass
