"""RAG-Grounded FAQ Answering"""

import logging
from typing import Optional

from app.conversation.text_utils import strip_thinking
from app.prompts import render_prompt
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.rag.vector_db import VectorDB
from app.services import knowledge_service

logger = logging.getLogger(__name__)

FALLBACK_ANSWER = "I don't have that information on hand, but I can connect you with someone who does."

# Words that make an utterance depend on what was just said. "What are
# they?" carries almost none of its own meaning — embedded alone it
# retrieves whatever happens to sit nearest in the knowledge base, which
# on a real call meant a follow-up about drinks matched the restaurant's
# founding story, and "does it come with a side?" matched the parking
# document.
_CONTEXT_DEPENDENT_WORDS = frozenset(
    {"it", "they", "them", "that", "this", "those", "these", "one", "ones", "there"}
)
# Very short utterances depend on context even without a pronoun ("let's
# hear it", "and the price?", "how many minutes early?").
#
# Kept deliberately tight. Expansion is not free: adding earlier turns to
# a question that already stands on its own dilutes the embedding and can
# push a real match below the relevance threshold — measured, with "are
# you open on christmas" going from a clean match to no match at all once
# the preceding turns were prepended. A question that names its own
# subject is searched exactly as the caller said it.
_SHORT_UTTERANCE_WORDS = 4


def _needs_conversation_context(message: str) -> bool:
    words = [word.strip(".,!?").lower() for word in message.split()]
    if len(words) <= _SHORT_UTTERANCE_WORDS:
        return True
    return any(word in _CONTEXT_DEPENDENT_WORDS for word in words)


def build_retrieval_query(history: list, message: str) -> str:
    """
    What to actually search the knowledge base for.

    A caller's words are only half a question in a real conversation:
    "does it come with a side?" means nothing without the dish named a
    turn earlier. So a follow-up is searched together with the caller's
    previous turn, rather than on its own.

    `history` is the conversation so far, most recent last, and already
    includes this message as its final turn.
    """
    if not _needs_conversation_context(message):
        return message

    # The caller's own previous turn, not the assistant's reply: what the
    # caller last asked about is the subject their follow-up refers to,
    # while the assistant's phrasing around it ("I'm sorry, could you
    # tell me a bit more about what you need?") is noise that pulls the
    # embedding away from the topic.
    previous_caller_turn = next(
        (turn.content for turn in reversed(history[:-1]) if turn.role == "caller"), ""
    )
    return f"{previous_caller_turn} {message}".strip()


async def generate_faq_answer(
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    vector_db: VectorDB,
    restaurant_id: str,
    restaurant_name: str,
    question: str,
    search_query: Optional[str] = None,
    conversation_context: str = "",
) -> tuple[str, bool]:
    """
    Answer a caller's question using only retrieved restaurant knowledge.

    search_query is what to retrieve on, when that should differ from the
    question itself — a follow-up like "does it come with a side?" has to
    be searched together with the turn that named the dish (see
    build_retrieval_query). The answer prompt still receives the caller's
    actual words, so the reply answers what they asked rather than the
    expanded search string.

    Returns (answer_text, was_grounded). was_grounded=False means nothing
    in the knowledge base cleared RAG_RELEVANCE_THRESHOLD — the caller
    gets FALLBACK_ANSWER, and the LLM is never invoked at all for an
    ungrounded question, so there's no path by which it could improvise
    an answer from its own general knowledge.
    """
    chunks = await knowledge_service.search_knowledge(
        vector_db, embedder, restaurant_id, search_query or question
    )

    # Per-turn tracing. Set LOG_LEVEL=DEBUG to follow a live call
    # decision by decision; off by default, because a line per turn
    # at WARNING is what makes a real warning impossible to see.
    logger.debug(
        f"generate_faq_answer: question={question!r} "
        f"search_query={(search_query or question)!r} chunks_found={len(chunks)}"
    )

    if not chunks:
        return FALLBACK_ANSWER, False

    retrieved_context = "\n".join(f"- {chunk.content}" for chunk in chunks)
    prompt = render_prompt(
        "rag_answer_generation.txt",
        restaurant_name=restaurant_name,
        retrieved_context=retrieved_context,
        question=question,
        conversation_context=conversation_context or "(this is the start of the call)",
    )
    raw = await llm.generate(prompt, temperature=0.3)
    answer = strip_thinking(raw)
    return (answer if answer else FALLBACK_ANSWER), True
