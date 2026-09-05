"""
Vector Database Integration

ChromaDB-backed storage for RAG-powered knowledge retrieval, with strict
per-restaurant tenant isolation enforced via metadata filtering on every
query and every delete.

Embeddings are computed by the application (via EmbeddingProvider), not
by ChromaDB itself — vectors are passed in pre-computed. This keeps
"what model produced this embedding" as an explicit, application-level
decision rather than an implicit default baked into the vector store
(ChromaDB's own default embedding function would otherwise silently pull
a small ONNX model from the internet on first use, which contradicts
this project's local-first, Ollama-centric design).
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

import chromadb
from chromadb.api.configuration import (
    CollectionConfigurationInternal,
    ConfigurationParameter,
    HNSWConfigurationInternal,
)
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings

# Built from the *Internal config classes directly, not chromadb's own
# public CollectionConfiguration/HNSWConfiguration convenience wrappers
# (chromadb.api.configuration) — those wrappers are real in 0.5.7, but
# their to_json() stamps the wrapper subclass's own name
# ("HNSWConfigurationInterface") as the payload's "_type" field, while
# the corresponding from_json() (called both by a local/embedded client
# and, going by shared code in chromadb/types.py, the server too) checks
# for the *Internal name and raises ValueError on the mismatch —
# reproduced directly against a local EphemeralClient. Building the
# *Internal classes ourselves sidesteps the bug entirely: verified this
# same construction round-trips successfully and actually persists
# "space": "cosine" in the collection's real configuration_json.
_COSINE_HNSW_CONFIG = CollectionConfigurationInternal(
    parameters=[
        ConfigurationParameter(
            name="hnsw_configuration",
            value=HNSWConfigurationInternal(parameters=[ConfigurationParameter(name="space", value="cosine")]),
        )
    ]
)

logger = logging.getLogger(__name__)

# ChromaDB 0.4.x's bundled posthog telemetry client raises on every call
# in this environment (a posthog API version mismatch: "capture() takes 1
# positional argument but 3 were given"). It's caught and logged as an
# error internally, not raised further, but that still floods logs with a
# spurious-looking error on every single collection operation. Silencing
# the logger is the documented workaround (anonymized_telemetry=False
# alone does not stop it in this chromadb version).
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

_COLLECTION_NAME = "restaurant_knowledge"


@dataclass
class RetrievedChunk:
    """One retrieved chunk of restaurant knowledge, with its similarity score."""

    chunk_id: str
    document_id: str
    content: str
    similarity: float
    metadata: dict[str, Any]


class VectorDB:
    """ChromaDB-backed vector store for restaurant knowledge chunks."""

    def __init__(self, client: chromadb.ClientAPI, collection_name: str = _COLLECTION_NAME):
        """
        Args:
            client: A ChromaDB client (HttpClient in production).
            collection_name: Defaults to the shared production collection.
                Tests pass a unique name per instance — chromadb's
                EphemeralClient caches its backing store keyed by client
                settings, so two `EphemeralClient()` instances in the same
                process (e.g. two pytest tests) silently share data under
                the same collection name unless given distinct names.
        """
        self._client = client
        self._collection = client.get_or_create_collection(
            name=collection_name,
            # Cosine distance is bounded to [0, 2] with a clean similarity
            # conversion (similarity = 1 - distance), and is the standard
            # metric for normalized text embeddings.
            #
            # Both `configuration` and `metadata` request cosine — only
            # `configuration` is what the server actually honors for the
            # real HNSW index metric (this client version's `metadata`
            # dict is stored as given but never derives the index config
            # from it — see the chromadb pin's own comment in
            # pyproject.toml). `metadata` is kept alongside it anyway:
            # harmless, and it's what shows up reading the collection
            # back via the API for a human checking its config.
            configuration=_COSINE_HNSW_CONFIG,
            metadata={"hnsw:space": "cosine"},
        )

    async def health_check(self) -> bool:
        try:
            self._client.heartbeat()
            return True
        except Exception as e:
            logger.error(f"Vector DB health check failed: {e}")
            return False

    async def add_chunks(
        self,
        restaurant_id: str,
        document_id: str,
        chunks: list[str],
        embeddings: list[list[float]],
        document_type: str,
        source: Optional[str] = None,
    ) -> list[str]:
        """
        Store embedded chunks for one document. Returns the chunk IDs
        (used as vector_ids on the RestaurantKnowledgeDocument row so a
        later delete/reindex knows exactly what to remove).
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must be the same length")
        if not chunks:
            return []

        chunk_ids = [f"{document_id}:{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "restaurant_id": restaurant_id,
                "document_id": document_id,
                "document_type": document_type,
                "source": source or "",
            }
            for _ in chunks
        ]

        self._collection.add(
            ids=chunk_ids,
            # chromadb's stubs declare embeddings/metadatas as covariant
            # Sequence unions, but our own list[list[float]] / list[dict]
            # types are invariant to mypy — a real runtime match, just an
            # overly narrow stub signature.
            embeddings=embeddings,  # type: ignore[arg-type]
            documents=chunks,
            metadatas=metadatas,  # type: ignore[arg-type]
        )
        return chunk_ids

    async def search(
        self,
        restaurant_id: str,
        query_embedding: list[float],
        top_k: int,
        relevance_threshold: float,
    ) -> list[RetrievedChunk]:
        """
        Retrieve the most relevant chunks for a query, scoped to one
        restaurant. Chunks below relevance_threshold are dropped — a
        caller getting no results back must be told "not in scope", not
        handed a low-confidence chunk to potentially hallucinate around.

        The restaurant_id filter is applied server-side via `where`, not
        after the fact in Python: a cross-tenant chunk must never even be
        considered a candidate, regardless of how it might score.
        """
        # An empty collection raises inside hnswlib rather than returning
        # zero results — treat "nothing indexed yet" as "no matches".
        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_embeddings=[query_embedding],  # type: ignore[arg-type]  # see add_chunks() note above
            n_results=top_k,
            where={"restaurant_id": restaurant_id},
        )

        chunks: list[RetrievedChunk] = []
        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        for chunk_id, content, metadata, distance in zip(ids, documents, metadatas, distances, strict=True):
            similarity = 1.0 - distance
            # Per-candidate tracing, for calibrating the relevance
            # thresholds against real caller phrasing. LOG_LEVEL=DEBUG.
            logger.debug(
                f"search candidate: content={content[:60]!r} similarity={similarity:.4f} "
                f"threshold={relevance_threshold} kept={similarity >= relevance_threshold}"
            )
            if similarity < relevance_threshold:
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=str(metadata["document_id"]),
                    content=content,
                    similarity=similarity,
                    metadata=dict(metadata),
                )
            )

        return chunks

    async def delete_document(self, restaurant_id: str, document_id: str) -> None:
        """
        Delete all chunks for one document.

        Filters by both restaurant_id and document_id — a restaurant can
        never delete another restaurant's vectors even if it somehow
        guessed a valid document_id. Chroma's `where` filter requires
        multiple conditions to be combined with an explicit "$and" —
        passing them as separate dict keys (implicit AND, as most query
        APIs allow) raises "Expected where to have exactly one operator".
        """
        self._collection.delete(
            where={"$and": [{"restaurant_id": restaurant_id}, {"document_id": document_id}]}
        )

    async def delete_restaurant(self, restaurant_id: str) -> None:
        """Delete every chunk belonging to a restaurant (e.g. on restaurant deletion)."""
        self._collection.delete(where={"restaurant_id": restaurant_id})


_client: Optional[chromadb.ClientAPI] = None
_vector_db: Optional[VectorDB] = None


def _build_client() -> chromadb.ClientAPI:
    """
    Build the ChromaDB client for VECTOR_DB_URL (host:port of the chromadb
    Docker service). httpx-style URLs are parsed manually since
    chromadb.HttpClient wants host/port/ssl separately, not a URL.
    """
    from urllib.parse import urlparse

    parsed = urlparse(settings.VECTOR_DB_URL)
    return chromadb.HttpClient(
        host=parsed.hostname or "localhost",
        port=str(parsed.port or 8000),
        ssl=parsed.scheme == "https",
        settings=ChromaSettings(anonymized_telemetry=False),
    )


async def get_vector_db() -> VectorDB:
    """Get the (lazily-initialized, process-wide) vector DB instance."""
    global _client, _vector_db
    if _vector_db is None:
        _client = _build_client()
        _vector_db = VectorDB(_client)
        logger.info(f"Vector DB initialized: {settings.VECTOR_DB_PROVIDER} at {settings.VECTOR_DB_URL}")
    return _vector_db
