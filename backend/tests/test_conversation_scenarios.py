"""
Whole conversations, not single turns.

Every scenario here is one a real caller actually put this system
through. A turn can be individually correct and still leave the caller
stuck — the four-yes loop below is four turns each of which did exactly
what its own branch said it should.
"""

import json

from app.conversation.engine import ConversationEngine
from app.conversation.state import ConversationContext, ConversationState
from app.services import knowledge_service
from tests.dates import FUTURE_DATE
from tests.fakes import ScriptedLLMProvider, contains


def _engine(llm, embedding_provider, vector_db, db_session, restaurant):
    return ConversationEngine(llm, embedding_provider, vector_db, db_session, restaurant)


async def _seed(db_session, vector_db, embedding_provider, restaurant, title, content):
    await knowledge_service.create_document(
        db_session, vector_db, embedding_provider, restaurant.id, title, content, "faq", None
    )
    await db_session.commit()


# ----------------------------------------------------------------------
# The caller says yes to "anything else?"
# ----------------------------------------------------------------------


async def test_saying_yes_to_anything_else_invites_the_question(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    Observed live: four consecutive turns of the caller saying "yes",
    "yeah", "OK", "yes" and hearing the closing question back every
    time, because a bare yes classified SMALLTALK and every smalltalk
    reply ends with that same closer.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    # A real answer first — a bare "yes" before anything was answered
    # isn't answering us, and must not be treated as though it were.
    await engine.handle_turn(context, "What time do you close tonight?")
    assert context.answered_something

    calls_before = len(llm.calls)
    replies = []
    for _ in range(4):
        replies.append((await engine.handle_turn(context, "yes")).response_text)

    # Never the closer again, and never the same line twice running.
    for reply in replies:
        assert "anything else" not in reply.lower()
    assert all(a != b for a, b in zip(replies, replies[1:], strict=False))
    # And it costs no model calls at all — this needs no classification.
    assert len(llm.calls) == calls_before


async def test_saying_no_to_anything_else_lets_the_caller_go(
    db_session, vector_db, embedding_provider, restaurant
):
    """A caller who has said they're done must not be asked again."""
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "What time do you close tonight?")
    result = await engine.handle_turn(context, "no thanks")

    assert "?" not in result.response_text
    assert "anything else" not in result.response_text.lower()


async def test_yes_to_a_specific_offer_answers_the_offer(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    When the answer ends by offering something with a topic, "yes" means
    "tell me that" — not "I have another question".
    """
    await _seed(
        db_session, vector_db, embedding_provider, restaurant, "Specials",
        "Do you have specials? Do you want to hear about our specials? Our specials are grilled sea bass and a lamb shank.",
    )

    answers = iter(
        [
            "We're open till ten. Do you want to hear about our specials?",
            "The specials are grilled sea bass and a lamb shank.",
        ]
    )
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
            (contains("using ONLY the information below"), lambda _p: next(answers)),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "do you have specials?")
    assert context.pending_question == "Do you want to hear about our specials?"

    result = await engine.handle_turn(context, "yes please")

    assert "sea bass" in result.response_text
    # The offer is consumed, so a second "yes" can't re-answer it.
    assert context.pending_question is None


async def test_a_bare_yes_before_anything_was_answered_is_not_hijacked(
    db_session, vector_db, embedding_provider, restaurant
):
    """Opening a call with "yes" isn't answering us — there was nothing
    to answer. It must still go through normal classification."""
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "SMALLTALK"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "yes")

    assert any("Respond with exactly one of these labels" in c for c in llm.calls)


# ----------------------------------------------------------------------
# A caller who changes their mind, mid-booking, twice
# ----------------------------------------------------------------------


async def test_a_caller_who_corrects_themselves_twice_ends_up_booked_correctly(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    "Hey, can I get a table tonight?" / "Uh, for four." / "Actually make
    that five." / "Around seven." / "No, seven thirty." — the caller
    changing their mind is normal speech, not an error path.
    """
    # One per turn, each carrying only what that utterance actually said.
    def _fields(**kw):
        base = {"customer_name": None, "customer_phone": None, "reservation_date": None,
                "reservation_time": None, "party_size": None, "special_notes": None}
        return json.dumps({**base, **kw})

    extractions = iter(
        [
            _fields(customer_name="Sam", customer_phone="5551234567",
                    reservation_date=FUTURE_DATE),   # "can I get a table tonight?"
            _fields(party_size=4),                   # "uh, for four"
            _fields(party_size=5),                   # "actually make that five"
            _fields(reservation_time="19:00"),       # "around seven"
            _fields(reservation_time="19:30"),       # "no, seven thirty"
        ]
    )
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (contains("Extract reservation details"), lambda _p: next(extractions)),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "hey, can I get a table tonight? Sam, 555-123-4567")
    await engine.handle_turn(context, "uh, for four")
    await engine.handle_turn(context, "actually make that five")
    await engine.handle_turn(context, "around seven")
    result = await engine.handle_turn(context, "no, seven thirty")

    # The last word on each detail wins, and the read-back says so.
    assert context.reservation_draft.party_size == 5
    assert context.reservation_draft.reservation_time == "19:30"
    assert context.state == ConversationState.RESERVATION_CONFIRMING
    assert "7:30 PM" in result.response_text
    assert "5" in result.response_text
