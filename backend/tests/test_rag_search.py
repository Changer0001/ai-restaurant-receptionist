"""
Tests for the core RAG retrieval logic (app.services.knowledge_service),
exercised directly against the service layer rather than through HTTP —
this is what app.conversation.rag_answer (Phase 4) calls to ground its
FAQ answers.

These are the tests that matter most for "RAG safety": a caller must
never receive another restaurant's knowledge, and an irrelevant query
must come back empty rather than returning the least-bad match.
"""

from app.services import knowledge_service


async def _seed(db, vector_db, embedder, restaurant_id, title, content, document_type="general"):
    return await knowledge_service.create_document(
        db, vector_db, embedder, restaurant_id, title, content, document_type, None
    )


async def test_search_finds_relevant_chunk(db_session, vector_db, embedding_provider):
    await _seed(
        db_session,
        vector_db,
        embedding_provider,
        "restaurant-a",
        "Seating",
        "We have a lovely outdoor patio with seating for twenty guests.",
    )
    await db_session.commit()

    results = await knowledge_service.search_knowledge(
        vector_db, embedding_provider, "restaurant-a", "Do you have outdoor patio seating?", relevance_threshold=0.0
    )
    assert len(results) >= 1
    assert "patio" in results[0].content


async def test_search_never_returns_another_restaurants_chunks(db_session, vector_db, embedding_provider):
    await _seed(db_session, vector_db, embedding_provider, "restaurant-a", "A's Menu", "A's secret parking information.")
    await _seed(db_session, vector_db, embedding_provider, "restaurant-b", "B's Menu", "B's secret parking information.")
    await db_session.commit()

    results_a = await knowledge_service.search_knowledge(
        vector_db, embedding_provider, "restaurant-a", "parking information", relevance_threshold=0.0
    )
    results_b = await knowledge_service.search_knowledge(
        vector_db, embedding_provider, "restaurant-b", "parking information", relevance_threshold=0.0
    )

    assert all(r.metadata["restaurant_id"] == "restaurant-a" for r in results_a)
    assert all(r.metadata["restaurant_id"] == "restaurant-b" for r in results_b)
    assert not any("B's secret" in r.content for r in results_a)
    assert not any("A's secret" in r.content for r in results_b)


async def test_search_with_no_indexed_knowledge_returns_empty(vector_db, embedding_provider):
    """An empty collection must not raise — it must mean 'nothing to ground on'."""
    results = await knowledge_service.search_knowledge(
        vector_db, embedding_provider, "restaurant-nonexistent", "anything at all"
    )
    assert results == []


async def test_search_respects_relevance_threshold(db_session, vector_db, embedding_provider):
    await _seed(
        db_session, vector_db, embedding_provider, "restaurant-a", "Hours", "We are open Monday through Friday, 9 to 5."
    )
    await db_session.commit()

    # A query sharing no vocabulary with the indexed content should score
    # near zero under the fake embedding provider's word-overlap scheme —
    # an unreasonably high threshold must filter it out entirely, which is
    # exactly the behavior that keeps the future AI layer from grounding
    # an answer on an irrelevant chunk.
    results = await knowledge_service.search_knowledge(
        vector_db,
        embedding_provider,
        "restaurant-a",
        "quantum flux capacitor spaceship",
        relevance_threshold=0.99,
    )
    assert results == []


async def test_search_respects_top_k(db_session, vector_db, embedding_provider):
    for i in range(5):
        await _seed(
            db_session, vector_db, embedding_provider, "restaurant-a", f"Doc {i}", f"Reservation policy detail number {i}."
        )
    await db_session.commit()

    results = await knowledge_service.search_knowledge(
        vector_db, embedding_provider, "restaurant-a", "reservation policy", top_k=2, relevance_threshold=0.0
    )
    assert len(results) <= 2


async def test_delete_document_removes_it_from_search(db_session, vector_db, embedding_provider):
    doc = await _seed(
        db_session, vector_db, embedding_provider, "restaurant-a", "Temp", "Unique unmistakable placeholder text."
    )
    await db_session.commit()

    before = await knowledge_service.search_knowledge(
        vector_db, embedding_provider, "restaurant-a", "unmistakable placeholder", relevance_threshold=0.0
    )
    assert len(before) >= 1

    await knowledge_service.delete_document(db_session, vector_db, "restaurant-a", doc.id)
    await db_session.commit()

    after = await knowledge_service.search_knowledge(
        vector_db, embedding_provider, "restaurant-a", "unmistakable placeholder", relevance_threshold=0.0
    )
    assert after == []
