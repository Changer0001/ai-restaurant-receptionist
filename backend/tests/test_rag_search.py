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


# ----------------------------------------------------------------------
# Confidence filtering
#
# A relevance floor alone isn't enough once a knowledge base has any
# breadth: on a real call, "what about holidays, Christmas, New Year's?"
# returned five chunks between 0.49 and 0.52 — mixed grill, halal,
# appetizers, parking, shawarma — none about holidays, and the model was
# handed all five and asked to answer.
# ----------------------------------------------------------------------

from app.rag.vector_db import RetrievedChunk  # noqa: E402
from app.services.knowledge_service import _keep_confident_matches  # noqa: E402


def _chunk(similarity: float, content: str = "x") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c",
        document_id="d",
        content=content,
        similarity=similarity,
        metadata={},
    )


def test_a_flat_cluster_just_above_the_floor_is_treated_as_no_answer():
    # The real scores from the holidays question.
    chunks = [_chunk(s) for s in (0.5174, 0.5017, 0.5004, 0.4930, 0.4883)]
    assert _keep_confident_matches(chunks) == []


def test_a_clear_winner_is_kept_and_its_weak_tail_dropped():
    # The real scores from "how many cars fit in your parking lot?".
    chunks = [_chunk(s) for s in (0.6314, 0.4658, 0.4541, 0.4525, 0.4507)]
    kept = _keep_confident_matches(chunks)
    assert [c.similarity for c in kept] == [0.6314]


def test_several_genuinely_strong_matches_are_all_kept():
    chunks = [_chunk(s) for s in (0.72, 0.68, 0.65, 0.44)]
    kept = _keep_confident_matches(chunks)
    assert [c.similarity for c in kept] == [0.72, 0.68, 0.65]


def test_no_chunks_stays_empty():
    assert _keep_confident_matches([]) == []
