"""
Tests for follow-up-aware retrieval (app.conversation.rag_answer's
build_retrieval_query).

Every case here is a real utterance from a live call. Searched on their
own, they retrieved nonsense: "what are they?" (asked right after the
assistant mentioned drinks) matched the restaurant's founding story and
then nothing at all, and "does it come with side?" matched the parking
document.
"""

from app.conversation.rag_answer import build_retrieval_query
from app.conversation.state import Turn


def _history(*turns: tuple[str, str]) -> list[Turn]:
    return [Turn(role=role, content=content) for role, content in turns]


def test_pronoun_followup_is_searched_with_the_previous_question():
    history = _history(
        ("caller", "Okay, what kind of drinks do you have?"),
        ("assistant", "We have tea, lemonade and a few soft drinks."),
        ("caller", "What are they?"),
    )
    query = build_retrieval_query(history, "What are they?")
    assert "drinks" in query
    assert "What are they?" in query


def test_followup_does_not_carry_the_assistants_own_words():
    """
    The assistant's phrasing is noise for retrieval — an apology or a
    "could you tell me more" pulls the embedding away from the topic the
    caller actually raised.
    """
    history = _history(
        ("caller", "asdkjf"),
        ("assistant", "I'm sorry, could you tell me a bit more about what you need?"),
        ("caller", "What about it?"),
    )
    query = build_retrieval_query(history, "What about it?")
    assert "sorry" not in query.lower()


def test_self_contained_question_is_searched_exactly_as_asked():
    """
    Expansion is not free — padding a question that already names its
    own subject dilutes the embedding and can drop a real match below
    the relevance threshold.
    """
    history = _history(
        ("caller", "asdkjf"),
        ("assistant", "I'm sorry, could you tell me a bit more about what you need?"),
        ("caller", "Are you open on Christmas?"),
    )
    assert build_retrieval_query(history, "Are you open on Christmas?") == "Are you open on Christmas?"


def test_a_longer_question_naming_its_subject_is_not_expanded():
    history = _history(("caller", "What are the sides for the mixed grill platter?"))
    query = build_retrieval_query(history, "What are the sides for the mixed grill platter?")
    assert query == "What are the sides for the mixed grill platter?"


def test_first_turn_followup_survives_having_no_history():
    history = _history(("caller", "How much is it?"))
    assert build_retrieval_query(history, "How much is it?") == "How much is it?"
