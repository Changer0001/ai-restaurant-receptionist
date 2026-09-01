"""
Integration tests for the conversation state machine (app.conversation.engine).

These are the tests that most directly exercise the spec's final
acceptance-test scenarios (minus the actual phone call, which is Phase
5): asking about hours, asking a knowledge-base question, booking a
table across multiple turns, requesting to order food, and an
unanswerable question that must not be hallucinated.
"""

import json

from app.conversation.engine import ConversationEngine
from app.conversation.state import ConversationContext, ConversationState
from app.services import knowledge_service
from tests.fakes import ScriptedLLMProvider, contains


def _engine(llm, embedding_provider, vector_db, db_session, restaurant):
    return ConversationEngine(llm, embedding_provider, vector_db, db_session, restaurant)


# ----------------------------------------------------------------------
# Hours (structured data, not RAG/LLM-generated)
# ----------------------------------------------------------------------


async def test_closing_time_question_answered_from_structured_hours(db_session, vector_db, embedding_provider, restaurant):
    # The LLM's only calls here should be escalation-check and intent
    # classification — hours answers never touch the LLM.
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "What time do you close tonight?")

    assert "close" in result.response_text.lower()
    assert result.state == ConversationState.IDENTIFY_INTENT
    assert not result.should_transfer


# ----------------------------------------------------------------------
# FAQ via RAG
# ----------------------------------------------------------------------


async def test_faq_grounded_in_knowledge_base(db_session, vector_db, embedding_provider, restaurant):
    # Phrased as an FAQ entry (question folded into the answer) rather
    # than free prose — this is both realistic (that's what an FAQ is)
    # and reliably clears cosine similarity under the fake embedding
    # provider's bag-of-words scheme, which — unlike a real embedding
    # model — has no semantic understanding that "patio" relates to
    # "outdoor seating" without literal word overlap.
    await knowledge_service.create_document(
        db_session,
        vector_db,
        embedding_provider,
        restaurant.id,
        "Seating",
        "Do you have outdoor seating? Yes, we have outdoor seating on our patio for twenty guests.",
        "policy",
        None,
    )
    await db_session.commit()

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
            (contains("using ONLY the information below"), "Yes, we have a lovely outdoor patio!"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "Do you have outdoor seating?")

    assert "patio" in result.response_text.lower()
    assert result.state == ConversationState.IDENTIFY_INTENT


async def test_ungrounded_faq_never_reaches_the_llm_for_an_answer(db_session, vector_db, embedding_provider, restaurant):
    """An empty knowledge base must produce the fallback answer without
    ever calling the LLM to generate a (potentially hallucinated) one."""
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
            (contains("using ONLY the information below"), "SHOULD NOT BE CALLED"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "Do you validate parking?")

    assert "don't have that information" in result.response_text
    assert not any("using ONLY the information below" in call for call in llm.calls)


# ----------------------------------------------------------------------
# Reservation flow (multi-turn)
# ----------------------------------------------------------------------


async def test_full_reservation_flow_creates_a_real_reservation(db_session, vector_db, embedding_provider, restaurant):
    extraction_responses = iter(
        [
            json.dumps({"customer_name": None, "customer_phone": None, "reservation_date": "2026-09-04", "reservation_time": "19:00", "party_size": 4, "special_notes": None}),
            json.dumps({"customer_name": "Jane Smith", "customer_phone": None, "reservation_date": None, "reservation_time": None, "party_size": None, "special_notes": None}),
            json.dumps({"customer_name": None, "customer_phone": "555-123-4567", "reservation_date": None, "reservation_time": None, "party_size": None, "special_notes": None}),
        ]
    )
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (contains("Extract reservation details"), lambda _p: next(extraction_responses)),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    r1 = await engine.handle_turn(context, "I'd like a table for four this Friday at 7")
    assert context.state == ConversationState.RESERVATION_COLLECTING
    assert "name" in r1.response_text.lower()

    r2 = await engine.handle_turn(context, "Jane Smith")
    assert context.state == ConversationState.RESERVATION_COLLECTING
    assert "phone" in r2.response_text.lower()

    r3 = await engine.handle_turn(context, "555-123-4567")
    assert context.state == ConversationState.RESERVATION_CONFIRMING
    assert "confirm" in r3.response_text.lower() and "Jane Smith" in r3.response_text

    r4 = await engine.handle_turn(context, "Yes that's correct", call_sid="CA123")
    assert r4.reservation is not None
    assert r4.reservation.status.value == "pending"
    assert r4.reservation.customer_name == "Jane Smith"
    assert r4.reservation.call_sid == "CA123"
    assert "submitted" in r4.response_text.lower()
    assert "confirmed" not in r4.response_text.lower()  # never overclaim
    assert context.state == ConversationState.IDENTIFY_INTENT
    assert context.reservation_draft.customer_name is None  # draft reset for next request


async def test_reservation_denial_returns_to_collecting(db_session, vector_db, embedding_provider, restaurant):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (
                contains("Extract reservation details"),
                json.dumps({"customer_name": "Bob", "customer_phone": "5551234567", "reservation_date": "2026-09-04", "reservation_time": "19:00", "party_size": 2, "special_notes": None}),
            ),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "Table for 2, Bob, Friday 7pm, 555-123-4567")
    assert context.state == ConversationState.RESERVATION_CONFIRMING

    result = await engine.handle_turn(context, "No that's wrong")
    assert context.state == ConversationState.RESERVATION_COLLECTING
    assert result.reservation is None


# ----------------------------------------------------------------------
# Ordering and escalation
# ----------------------------------------------------------------------


async def test_order_request_offers_a_transfer_without_taking_the_order(db_session, vector_db, embedding_provider, restaurant):
    """The engine asks before transferring (see ConversationState.CONFIRM_TRANSFER's
    docstring) rather than forcing a handoff on its own judgment — it must not
    silently transfer, and must not try to take the order itself."""
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "I want to order two burgers")

    assert result.should_transfer is False
    assert context.state == ConversationState.CONFIRM_TRANSFER
    assert context.transfer_reason == "order_request"
    assert "order" not in result.response_text.lower().replace("orders directly", "").replace("your order", "")


async def test_confirmed_order_transfer_actually_transfers(db_session, vector_db, embedding_provider, restaurant):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "I want to order two burgers")
    result = await engine.handle_turn(context, "Yes please")

    assert result.should_transfer is True
    assert result.transfer_reason == "order_request"
    assert context.state == ConversationState.TRANSFER_TO_HUMAN


async def test_declined_transfer_returns_to_identify_intent(db_session, vector_db, embedding_provider, restaurant):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "I want to order two burgers")
    result = await engine.handle_turn(context, "No, never mind")

    assert result.should_transfer is False
    assert context.state == ConversationState.IDENTIFY_INTENT
    assert context.transfer_reason is None


async def test_explicit_human_request_transfers(db_session, vector_db, embedding_provider, restaurant):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "HUMAN"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "Can I speak to someone?")

    assert result.should_transfer is True
    assert result.transfer_reason == "caller_requested_human"


async def test_sentiment_based_escalation_short_circuits_intent_classification(db_session, vector_db, embedding_provider, restaurant):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "YES"),
            (contains("Respond with exactly one of these labels"), "SHOULD NOT BE CALLED"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "This is ridiculous, nobody is helping me!")

    # Offers a transfer rather than forcing one — see
    # ConversationState.CONFIRM_TRANSFER's docstring.
    assert result.should_transfer is False
    assert context.state == ConversationState.CONFIRM_TRANSFER
    assert context.transfer_reason == "escalation"
    assert not any("Respond with exactly one of these labels" in call for call in llm.calls)

    result2 = await engine.handle_turn(context, "Yes, connect me")
    assert result2.should_transfer is True
    assert result2.transfer_reason == "escalation"
    assert context.state == ConversationState.TRANSFER_TO_HUMAN


async def test_repeated_unclear_intent_offers_a_transfer(db_session, vector_db, embedding_provider, restaurant):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "UNCLEAR"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    r1 = await engine.handle_turn(context, "asdkjf")
    assert r1.should_transfer is False
    assert context.state == ConversationState.IDENTIFY_INTENT

    r2 = await engine.handle_turn(context, "asdkjf again")
    # Offers a transfer rather than forcing one — see
    # ConversationState.CONFIRM_TRANSFER's docstring.
    assert r2.should_transfer is False
    assert context.state == ConversationState.CONFIRM_TRANSFER
    assert context.transfer_reason == "repeated_unclear"

    r3 = await engine.handle_turn(context, "sure, go ahead")
    assert r3.should_transfer is True
    assert r3.transfer_reason == "repeated_unclear"
    assert context.state == ConversationState.TRANSFER_TO_HUMAN


async def test_unclear_count_resets_after_successful_intent(db_session, vector_db, embedding_provider, restaurant):
    responses = iter(["UNCLEAR", "FAQ", "UNCLEAR"])
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), lambda _p: next(responses)),
            (contains("using ONLY the information below"), "We're closed on Christmas."),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "asdkjf")
    assert context.unclear_count == 1

    await engine.handle_turn(context, "are you open on christmas")
    assert context.unclear_count == 0  # reset by the successful FAQ classification

    result = await engine.handle_turn(context, "asdkjf")
    assert context.unclear_count == 1
    assert result.should_transfer is False  # only one UNCLEAR since the reset
