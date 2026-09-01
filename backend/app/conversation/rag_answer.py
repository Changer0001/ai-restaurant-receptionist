"""RAG-Grounded FAQ Answering"""

import logging

from app.conversation.text_utils import strip_thinking
from app.prompts import render_prompt
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.rag.vector_db import VectorDB
from app.services import knowledge_service

logger = logging.getLogger(__name__)

FALLBACK_ANSWER = "I don't have that information on hand, but I can connect you with someone who does."


async def generate_faq_answer(
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    vector_db: VectorDB,
    restaurant_id: str,
    restaurant_name: str,
    question: str,
) -> tuple[str, bool]:
    """
    Answer a caller's question using only retrieved restaurant knowledge.

    Returns (answer_text, was_grounded). was_grounded=False means nothing
    in the knowledge base cleared RAG_RELEVANCE_THRESHOLD — the caller
    gets FALLBACK_ANSWER, and the LLM is never invoked at all for an
    ungrounded question, so there's no path by which it could improvise
    an answer from its own general knowledge.
    """
    chunks = await knowledge_service.search_knowledge(vector_db, embedder, restaurant_id, question)

    # TEMPORARY debug logging — remove once it's confirmed FAQ questions
    # (menu/parking/location) are finding grounded content.
    logger.warning(f"DEBUG generate_faq_answer: question={question!r} chunks_found={len(chunks)}")

    if not chunks:
        return FALLBACK_ANSWER, False

    retrieved_context = "\n".join(f"- {chunk.content}" for chunk in chunks)
    prompt = render_prompt(
        "rag_answer_generation.txt",
        restaurant_name=restaurant_name,
        retrieved_context=retrieved_context,
        question=question,
    )
    raw = await llm.generate(prompt, temperature=0.3)
    answer = strip_thinking(raw)
    return (answer if answer else FALLBACK_ANSWER), True
