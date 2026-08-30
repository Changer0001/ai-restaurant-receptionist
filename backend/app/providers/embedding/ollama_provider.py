"""
Ollama Embedding Provider

Local embedding inference via Ollama, using an embedding-specific model
(e.g. nomic-embed-text) rather than the chat/generation model.
"""

import logging
from typing import List

import httpx

from app.core.config import settings
from app.providers.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Ollama-based embedding provider for local, GPU-accelerated embeddings.

    Uses Ollama's single-text /api/embeddings endpoint (present since
    Ollama's earliest embedding support) rather than the newer batched
    /api/embed endpoint, since it's the more widely-deployed API surface;
    texts are embedded sequentially. Chunk counts per document are modest
    (RAG_CHUNK_SIZE keeps chunks small), so this isn't a throughput
    concern in practice.
    """

    def __init__(
        self,
        base_url: str = settings.OLLAMA_BASE_URL,
        model: str = settings.EMBEDDING_MODEL,
        timeout: int = settings.OLLAMA_REQUEST_TIMEOUT,
    ):
        self.base_url = base_url
        self.model = model
        self.client = httpx.AsyncClient(timeout=timeout)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts, one Ollama request per text."""
        embeddings: List[List[float]] = []
        for text in texts:
            try:
                response = await self.client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embedding = data.get("embedding")
                if not embedding:
                    raise ValueError(f"Ollama returned no embedding for model {self.model!r}")
                embeddings.append([float(x) for x in embedding])
            except httpx.HTTPError as e:
                logger.error(f"Ollama embedding error: {e}")
                raise
        return embeddings

    async def health_check(self) -> bool:
        """Check if Ollama is accessible and the embedding model responds."""
        try:
            await self.embed(["health check"])
            return True
        except Exception as e:
            logger.error(f"Ollama embedding health check failed: {e}")
            return False

    async def close(self) -> None:
        await self.client.aclose()
