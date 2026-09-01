"""
Restaurant knowledge-base business logic: ingestion, retrieval, deletion.

This is the RAG pipeline's application layer — it owns the "chunk, embed,
store, and keep the PostgreSQL row and the vector store in agreement"
orchestration that neither VectorDB nor EmbeddingProvider know about on
their own.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import RestaurantKnowledgeDocument
from app.providers.embedding.base import EmbeddingProvider
from app.rag.chunking import chunk_text
from app.rag.vector_db import RetrievedChunk, VectorDB

logger = logging.getLogger(__name__)


async def create_document(
    db: AsyncSession,
    vector_db: VectorDB,
    embedder: EmbeddingProvider,
    restaurant_id: str,
    title: str,
    content: str,
    document_type: str,
    source: str | None,
) -> RestaurantKnowledgeDocument:
    """Chunk, embed, and index a new knowledge document for a restaurant."""
    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document content is empty",
        )

    document = RestaurantKnowledgeDocument(
        restaurant_id=restaurant_id,
        title=title,
        content=content,
        document_type=document_type,
        source=source,
        is_active=True,
        vector_ids=[],
    )
    db.add(document)
    await db.flush()  # populates document.id

    vector_ids = await _index_document(vector_db, embedder, restaurant_id, document.id, content, document_type, source)
    document.vector_ids = vector_ids

    await db.flush()
    await db.refresh(document)
    return document


async def list_documents(db: AsyncSession, restaurant_id: str) -> list[RestaurantKnowledgeDocument]:
    result = await db.execute(
        select(RestaurantKnowledgeDocument)
        .where(RestaurantKnowledgeDocument.restaurant_id == restaurant_id)
        .order_by(RestaurantKnowledgeDocument.title)
    )
    return list(result.scalars().all())


async def _get_document_or_404(
    db: AsyncSession, restaurant_id: str, document_id: str
) -> RestaurantKnowledgeDocument:
    result = await db.execute(
        select(RestaurantKnowledgeDocument).where(
            RestaurantKnowledgeDocument.id == document_id,
            RestaurantKnowledgeDocument.restaurant_id == restaurant_id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found")
    return document


async def delete_document(
    db: AsyncSession, vector_db: VectorDB, restaurant_id: str, document_id: str
) -> None:
    document = await _get_document_or_404(db, restaurant_id, document_id)
    await vector_db.delete_document(restaurant_id, document_id)
    await db.delete(document)
    await db.flush()


async def reindex_document(
    db: AsyncSession,
    vector_db: VectorDB,
    embedder: EmbeddingProvider,
    restaurant_id: str,
    document_id: str,
) -> RestaurantKnowledgeDocument:
    """
    Re-chunk and re-embed a document's existing content — useful after a
    chunk-size/overlap config change, or to recover from a partial
    failure that left stale vectors behind.
    """
    document = await _get_document_or_404(db, restaurant_id, document_id)

    await vector_db.delete_document(restaurant_id, document_id)
    vector_ids = await _index_document(
        vector_db, embedder, restaurant_id, document.id, document.content, document.document_type, document.source
    )
    document.vector_ids = vector_ids

    await db.flush()
    await db.refresh(document)
    return document


def _keep_confident_matches(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Drop results that clear the relevance floor without actually
    answering anything.

    Two rules, both from measured behavior on real calls:

    1. If even the best chunk doesn't reach RAG_CONFIDENT_THRESHOLD,
       return nothing. A question the documents genuinely don't cover
       produces a flat cluster just above the floor rather than silence —
       "what about holidays, Christmas, New Year's?" returned five chunks
       between 0.49 and 0.52, none of which mentioned holidays, and the
       model was asked to answer holiday hours from them.

    2. Drop anything much weaker than the best chunk. A question that IS
       covered has a clear winner ("how many cars fit in your parking
       lot?" -> 0.63 with a tail at 0.46); the tail is just other
       documents about other things, and handing it to the model only
       invites an answer drawn from the wrong one.

    Chunks arrive best-first from the vector store.
    """
    if not chunks:
        return []

    best = chunks[0].similarity
    if best < settings.RAG_CONFIDENT_THRESHOLD:
        return []

    cutoff = best - settings.RAG_RELATIVE_MARGIN
    return [chunk for chunk in chunks if chunk.similarity >= cutoff]


async def search_knowledge(
    vector_db: VectorDB,
    embedder: EmbeddingProvider,
    restaurant_id: str,
    query: str,
    top_k: int | None = None,
    relevance_threshold: float | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve the most relevant knowledge chunks for a caller's question,
    scoped strictly to one restaurant. An empty result means "grounded
    knowledge doesn't cover this" — callers (the future AI conversation
    layer) must treat that as "I don't have that information", never as
    license to answer from the model's own general knowledge.
    """
    query_embedding = (await embedder.embed([query]))[0]
    chunks = await vector_db.search(
        restaurant_id=restaurant_id,
        query_embedding=query_embedding,
        top_k=top_k or settings.RAG_RETRIEVAL_TOP_K,
        relevance_threshold=relevance_threshold if relevance_threshold is not None else settings.RAG_RELEVANCE_THRESHOLD,
    )

    # An explicit threshold means the caller is asking for exactly what
    # clears that bar (tests, the admin search API) — don't second-guess
    # it. The confidence rules below are for a live phone call, where
    # answering from a weak match is worse than admitting a gap.
    if relevance_threshold is not None:
        return chunks

    return _keep_confident_matches(chunks)


async def _index_document(
    vector_db: VectorDB,
    embedder: EmbeddingProvider,
    restaurant_id: str,
    document_id: str,
    content: str,
    document_type: str,
    source: str | None,
) -> list[str]:
    chunks = chunk_text(content, settings.RAG_CHUNK_SIZE, settings.RAG_CHUNK_OVERLAP)
    if not chunks:
        return []

    embeddings = await embedder.embed(chunks)
    return await vector_db.add_chunks(
        restaurant_id=restaurant_id,
        document_id=document_id,
        chunks=chunks,
        embeddings=embeddings,
        document_type=document_type,
        source=source,
    )
