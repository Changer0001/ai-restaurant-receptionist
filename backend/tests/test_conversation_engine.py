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
from app.core.config import settings
from app.services import knowledge_service
from tests.dates import FUTURE_DATE
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
    """An empty knowledge base must offer a human handoff without ever
    calling the LLM to generate a (potentially hallucinated) answer."""
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

    assert not any("using ONLY the information below" in call for call in llm.calls)
    # The offer must actually park the call in CONFIRM_TRANSFER: saying
    # "I can connect you" and then dropping back to intent classification
    # leaves the caller's "yes please" landing as a brand-new request,
    # so the promised connection never happens — hit live.
    assert result.state == ConversationState.CONFIRM_TRANSFER
    assert "connect you" in result.response_text


async def test_confirming_an_ungrounded_faq_offer_transfers_the_call(
    db_session, vector_db, embedding_provider, restaurant
):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "Do you validate parking?")
    result = await engine.handle_turn(context, "Yes please")

    assert result.should_transfer is True
    assert result.state == ConversationState.TRANSFER_TO_HUMAN


# ----------------------------------------------------------------------
# Reservation flow (multi-turn)
# ----------------------------------------------------------------------


async def test_reservation_offers_a_transfer_when_collection_is_disabled(
    db_session, vector_db, embedding_provider, restaurant, monkeypatch
):
    """
    FEATURE_RESERVATION_COLLECTION=False is for a restaurant with no
    reservation system of its own to write a collected reservation
    into — a reservation request should offer a human handoff instead
    of the AI trying to collect the details itself.
    """
    monkeypatch.setattr(settings, "FEATURE_RESERVATION_COLLECTION", False)

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "I'd like a table for four this Friday at 7")

    assert result.should_transfer is False
    assert context.state == ConversationState.CONFIRM_TRANSFER
    assert context.transfer_reason == "reservation_request"
    assert not any("Extract reservation details" in call for call in llm.calls)

    result2 = await engine.handle_turn(context, "Yes, please")
    assert result2.should_transfer is True
    assert result2.transfer_reason == "reservation_request"
    assert context.state == ConversationState.TRANSFER_TO_HUMAN


async def test_a_restaurant_can_opt_out_of_reservations_on_a_deployment_that_takes_them(
    db_session, vector_db, embedding_provider, restaurant, monkeypatch
):
    """
    One process serves several restaurants, so "do we take bookings?" is
    a property of the client, not of the deployment. A walk-ins-only
    place must be able to say no without every other restaurant on the
    same box losing its reservation flow.
    """
    monkeypatch.setattr(settings, "FEATURE_RESERVATION_COLLECTION", True)
    restaurant.takes_reservations = False

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "I'd like a table for four this Friday at 7")

    assert context.state == ConversationState.CONFIRM_TRANSFER
    assert context.transfer_reason == "reservation_request"
    assert not any("Extract reservation details" in call for call in llm.calls)


async def test_a_restaurant_can_opt_in_on_a_deployment_that_does_not_take_them(
    db_session, vector_db, embedding_provider, restaurant, monkeypatch
):
    """The override has to work in both directions, or half the clients
    on a shared deployment need a code change to be onboarded."""
    monkeypatch.setattr(settings, "FEATURE_RESERVATION_COLLECTION", False)
    restaurant.takes_reservations = True

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (
                contains("Extract reservation details"),
                json.dumps(
                    {
                        "customer_name": None,
                        "customer_phone": None,
                        "reservation_date": FUTURE_DATE,
                        "reservation_time": "19:00",
                        "party_size": 4,
                        "special_notes": None,
                    }
                ),
            ),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "I'd like a table for four this Friday at 7")

    assert context.state == ConversationState.RESERVATION_COLLECTING
    assert any("Extract reservation details" in call for call in llm.calls)


async def test_full_reservation_flow_creates_a_real_reservation(db_session, vector_db, embedding_provider, restaurant):
    extraction_responses = iter(
        [
            json.dumps({"customer_name": None, "customer_phone": None, "reservation_date": FUTURE_DATE, "reservation_time": "19:00", "party_size": 4, "special_notes": None}),
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
    assert "number" in r2.response_text.lower()

    r3 = await engine.handle_turn(context, "555-123-4567")
    assert context.state == ConversationState.RESERVATION_CONFIRMING
    # Reads the booking back and asks for the go-ahead before creating
    # anything — the wording is deliberately a person's ("shall I put
    # that in") rather than software's ("submit this request").
    assert "Jane Smith" in r3.response_text
    assert r3.response_text.rstrip().endswith("?")

    r4 = await engine.handle_turn(context, "Yes that's correct", call_sid="CA123")
    assert r4.reservation is not None
    assert r4.reservation.status.value == "pending"
    assert r4.reservation.customer_name == "Jane Smith"
    assert r4.reservation.call_sid == "CA123"
    # Must NOT promise a confirmed table: this is a request the
    # restaurant still has to accept, and a caller who turns up
    # believing they have a booking is the worst outcome here.
    assert "confirm" in r4.response_text.lower()
    assert "you're booked" not in r4.response_text.lower()
    assert "reserved" not in r4.response_text.lower()
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
                json.dumps({"customer_name": "Bob", "customer_phone": "5551234567", "reservation_date": FUTURE_DATE, "reservation_time": "19:00", "party_size": 2, "special_notes": None}),
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


async def test_asking_who_picked_up_never_transfers_the_caller(db_session, vector_db, embedding_provider, restaurant):
    """
    "What was your name?" came back from the classifier as HUMAN on a
    real call and transferred the caller to the restaurant. Asking who
    answered the phone is a question about the assistant, not a request
    to be handed to somebody else — so it must not transfer even when
    the classifier says HUMAN.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "HUMAN"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "What was your name?")

    assert result.should_transfer is False
    assert context.state == ConversationState.IDENTIFY_INTENT
    assert restaurant.name in result.response_text


async def test_acknowledgement_gets_a_natural_reply_not_a_request_to_repeat(
    db_session, vector_db, embedding_provider, restaurant
):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "SMALLTALK"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.unclear_count = 1

    result = await engine.handle_turn(context, "Okay, thanks.")

    assert "sorry" not in result.response_text.lower()
    assert result.should_transfer is False
    assert context.state == ConversationState.IDENTIFY_INTENT
    # Small talk is a successful turn, so it clears the run of unclear
    # ones — otherwise politeness accumulates toward an escalation.
    assert context.unclear_count == 0


async def test_sentiment_based_escalation_wins_over_the_classified_intent(db_session, vector_db, embedding_provider, restaurant):
    """
    Escalation and intent classification are issued together to save a
    network round trip per turn, so intent IS classified even for an
    escalating message — its result just has to lose. An upset caller
    whose words also parse as a normal FAQ must still be offered a human.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "YES"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
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
    # The middle turn has to be a *grounded* FAQ answer to leave the
    # conversation in IDENTIFY_INTENT: an ungrounded one now offers a
    # transfer and parks in CONFIRM_TRANSFER, where the third turn would
    # be read as an answer to that offer rather than a new request.
    # Phrased FAQ-style for the fake embedder's literal word overlap —
    # see test_faq_grounded_in_knowledge_base.
    await knowledge_service.create_document(
        db_session,
        vector_db,
        embedding_provider,
        restaurant.id,
        "Holiday hours",
        "Are you open on Christmas? We're closed on Christmas.",
        "policy",
        None,
    )
    await db_session.commit()

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


async def test_asking_about_an_existing_booking_does_not_start_a_new_one(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    A real caller booked a table and, a few turns later, asked "can you
    remind me my reservation?" — and was walked through booking from
    scratch again: name, phone number, party size, all for a table they
    already had.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (contains("Extract reservation details"), "SHOULD NOT BE CALLED"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(
        restaurant_id=restaurant.id,
        known_reservation="I have you down for 5 people on Friday, September 4 at 7 PM, under Mike.",
    )

    result = await engine.handle_turn(context, "Can you remind me my reservation?")

    assert "5 people" in result.response_text
    assert "Mike" in result.response_text
    assert context.state == ConversationState.IDENTIFY_INTENT
    assert not any("Extract reservation details" in call for call in llm.calls)


async def test_booking_a_new_table_still_works_for_a_caller_who_already_has_one(
    db_session, vector_db, embedding_provider, restaurant, monkeypatch
):
    """The recall path must not swallow a genuine new booking request."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "FEATURE_RESERVATION_COLLECTION", False)
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(
        restaurant_id=restaurant.id,
        known_reservation="I have you down for 5 people on Friday, September 4 at 7 PM, under Mike.",
    )

    result = await engine.handle_turn(context, "I'd like to book a table for tomorrow at six")

    assert "5 people" not in result.response_text
    assert context.state == ConversationState.CONFIRM_TRANSFER


# ----------------------------------------------------------------------
# Confirm/deny matching
# ----------------------------------------------------------------------


async def test_a_word_containing_no_is_not_read_as_declining(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    "You are not answering my question" was matched against "no" by
    substring and treated as declining the transfer — so the caller got
    neither their question answered nor the transfer they'd asked for.
    """
    from app.conversation.engine import _says_any_of

    assert _says_any_of("no", ("no",))
    assert _says_any_of("No, thanks", ("no",))
    assert not _says_any_of("You are not answering my question", ("no",))
    assert not _says_any_of("I don't know the address", ("no",))
    assert not _says_any_of("Can I order now?", ("no",))


async def test_sure_is_accepted_as_a_confirmation(
    db_session, vector_db, embedding_provider, restaurant
):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "I'd like to place an order")
    result = await engine.handle_turn(context, "Sure")

    assert result.should_transfer is True


async def test_a_question_during_a_transfer_offer_gets_answered(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    A caller answered a transfer offer with "sure, but before you
    transfer me, can you tell me what's your name?" — and got the offer
    repeated back verbatim, twice, until they said "you are not
    answering my question."
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    await engine.handle_turn(context, "I'd like to place an order")
    result = await engine.handle_turn(context, "Before that, what's your name?")

    assert restaurant.name in result.response_text
    # The offer is still on the table — answering the aside must not
    # quietly drop what the caller was in the middle of.
    assert context.state == ConversationState.CONFIRM_TRANSFER
    assert "connect you" in result.response_text


async def test_out_of_scope_questions_are_declined_without_a_pointless_transfer(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    "What's the weather like?" and "how's the traffic?" cycled through
    "could you tell me a bit more about what you need?" and then pulled
    the seating and parking documents to answer from. A restaurant can't
    tell you the weather, and transferring the caller to a team member
    for it helps nobody.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "OUT_OF_SCOPE"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)

    result = await engine.handle_turn(context, "What's the weather like today?")

    assert result.should_transfer is False
    assert context.state == ConversationState.IDENTIFY_INTENT
    assert "sorry, could you tell me" not in result.response_text.lower()


async def test_a_caller_is_not_asked_for_the_number_they_are_calling_from(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    Asking someone to read out the number they're calling from is the
    clearest "this isn't really listening" moment a phone line has. On a
    real call it also cost a turn and came back from speech recognition
    as "619-689." with the last four digits missing.
    """
    import json as _json

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (
                contains("Extract reservation details"),
                _json.dumps(
                    {
                        "customer_name": None,
                        "customer_phone": None,
                        "reservation_date": FUTURE_DATE,
                        "reservation_time": "19:00",
                        "party_size": 4,
                        "special_notes": None,
                    }
                ),
            ),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(
        restaurant_id=restaurant.id,
        caller_number="+15551234567",
        caller_name="Mike",
    )

    result = await engine.handle_turn(context, "A table for four on Friday at 7")

    # Name and number both already known, so the only thing left is the
    # read-back — no questions asked for either.
    assert context.state == ConversationState.RESERVATION_CONFIRMING
    assert context.reservation_draft.customer_phone == "+15551234567"
    assert context.reservation_draft.customer_name == "Mike"
    # Taken from caller ID rather than spoken, so it's confirmed rather
    # than silently assumed.
    assert "number you're calling from" in result.response_text


async def test_a_caller_booking_on_someone_elses_behalf_can_still_correct_the_details(
    db_session, vector_db, embedding_provider, restaurant
):
    """Prefilled details are a default, not a decision — "no" reopens them."""
    import json as _json

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (
                contains("Extract reservation details"),
                _json.dumps(
                    {
                        "customer_name": None,
                        "customer_phone": None,
                        "reservation_date": FUTURE_DATE,
                        "reservation_time": "19:00",
                        "party_size": 4,
                        "special_notes": None,
                    }
                ),
            ),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(
        restaurant_id=restaurant.id, caller_number="+15551234567", caller_name="Mike"
    )

    await engine.handle_turn(context, "A table for four on Friday at 7")
    result = await engine.handle_turn(context, "No, that's wrong")

    assert context.state == ConversationState.RESERVATION_COLLECTING
    assert "change" in result.response_text.lower()


# ----------------------------------------------------------------------
# Getting out of a flow the caller no longer wants
#
# Every case below is from one real call. The reservation flow had no
# exit at all: once collecting, every utterance went to slot extraction,
# so the caller said "I don't want to make reservation", "I just want to
# cancel the reservation" and "no, I would like to place an order" — and
# a reservation was created anyway.
# ----------------------------------------------------------------------


async def test_cancelling_mid_booking_does_not_create_a_reservation(
    db_session, vector_db, embedding_provider, restaurant
):
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "SMALLTALK"),
            (contains("Extract reservation details"), "SHOULD NOT BE CALLED"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.state = ConversationState.RESERVATION_COLLECTING

    await engine.handle_turn(context, "I just want to cancel the reservation")

    assert context.state == ConversationState.IDENTIFY_INTENT
    assert context.reservation_draft.missing_fields()  # draft was thrown away
    assert not any("Extract reservation details" in call for call in llm.calls)


async def test_changing_to_an_order_mid_booking_is_acted_on_immediately(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    "no, I would like to place an order" during a booking must not be
    read as booking details, and must not cost the caller another turn
    to repeat themselves.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "ORDER"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.state = ConversationState.RESERVATION_COLLECTING

    result = await engine.handle_turn(context, "No, I would like to place an order")

    assert context.state == ConversationState.CONFIRM_TRANSFER
    assert context.transfer_reason == "order_request"
    assert "order" in result.response_text.lower()


async def test_refusing_at_the_readback_does_not_book_the_table(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    A caller said "No, I don't want you to put that in", then "I just
    want to cancel the reservation" — and the booking was still created.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "SMALLTALK"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.state = ConversationState.RESERVATION_CONFIRMING

    result = await engine.handle_turn(context, "Actually cancel that, I've changed my mind")

    assert result.reservation is None
    assert context.state == ConversationState.IDENTIFY_INTENT


async def test_a_question_during_a_transfer_offer_is_answered_not_re_offered(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    A caller asked about arriving early, was offered a transfer, asked
    again, was offered again, and said "well, I'm asking you if I arrive
    early." The offer must give way to the question.
    """
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "SMALLTALK"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.state = ConversationState.CONFIRM_TRANSFER
    context.transfer_reason = "unknown_answer"

    result = await engine.handle_turn(context, "Well, I'm asking you if I arrive early")

    assert "connect you" not in result.response_text.lower()
    assert context.state != ConversationState.CONFIRM_TRANSFER


async def test_a_long_reply_starting_with_no_is_not_read_as_declining(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    "not yet, I just need a reservation for 7 o'clock tomorrow" was heard
    as "no" and the reservation request was thrown away.
    """
    import json as _json

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (
                contains("Extract reservation details"),
                _json.dumps(
                    {
                        "customer_name": None,
                        "customer_phone": None,
                        "reservation_date": FUTURE_DATE,
                        "reservation_time": "19:00",
                        "party_size": None,
                        "special_notes": None,
                    }
                ),
            ),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.state = ConversationState.CONFIRM_TRANSFER
    context.transfer_reason = "escalation"

    await engine.handle_turn(context, "Not yet, I just need a reservation for 7 o'clock tomorrow")

    # The reservation request was heard, not discarded as a "no".
    assert context.state in (
        ConversationState.RESERVATION_COLLECTING,
        ConversationState.RESERVATION_CONFIRMING,
    )


async def test_a_short_no_still_declines_the_transfer(
    db_session, vector_db, embedding_provider, restaurant
):
    """The fix above must not break the ordinary one-word answer."""
    llm = ScriptedLLMProvider([])
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.state = ConversationState.CONFIRM_TRANSFER
    context.transfer_reason = "escalation"

    result = await engine.handle_turn(context, "No.")

    assert result.should_transfer is False
    assert context.state == ConversationState.IDENTIFY_INTENT


async def test_a_short_yes_still_accepts_the_transfer(
    db_session, vector_db, embedding_provider, restaurant
):
    llm = ScriptedLLMProvider([])
    engine = _engine(llm, embedding_provider, vector_db, db_session, restaurant)
    context = ConversationContext(restaurant_id=restaurant.id)
    context.state = ConversationState.CONFIRM_TRANSFER
    context.transfer_reason = "order_request"

    result = await engine.handle_turn(context, "Yes please")

    assert result.should_transfer is True
    assert result.transfer_reason == "order_request"


# ----------------------------------------------------------------------
# Reading a yes or a no
#
# These two branches decide whether a reservation gets written and
# whether a call gets handed to a person, so a misread costs the caller
# something real. Every case below is a phrasing that was mishandled.
# ----------------------------------------------------------------------


def test_a_refusal_containing_a_polite_word_is_not_a_confirmation():
    """
    "please" was a confirm word and confirm was tested before deny, so
    "no, please don't" read as YES — booking a table for a caller who
    had just said not to.
    """
    from app.conversation.engine import _reads_as

    assert _reads_as("no, please don't") == "deny"
    assert _reads_as("no please") == "deny"
    assert _reads_as("no thanks") == "deny"
    assert _reads_as("not yet") == "deny"


def test_an_affirmative_idiom_containing_no_is_still_a_yes():
    """The precedence above must not swallow the ways people say yes."""
    from app.conversation.engine import _reads_as

    assert _reads_as("sure, no problem") == "confirm"
    assert _reads_as("no problem") == "confirm"
    assert _reads_as("why not") == "confirm"
    assert _reads_as("yes please") == "confirm"
    assert _reads_as("please do") == "confirm"
    assert _reads_as("go ahead") == "confirm"


def test_an_utterance_that_is_neither_reads_as_neither():
    from app.conversation.engine import _reads_as

    assert _reads_as("what time did you say") is None
    assert _reads_as("hmm") is None


def test_asking_about_the_cancellation_policy_does_not_abandon_the_booking():
    """
    Substring matching put "cancel" inside "cancellation", so a caller
    mid-booking who asked about the cancellation policy had their
    half-finished reservation thrown away and their question ignored.
    """
    from app.conversation.engine import _wants_out_of_reservation

    assert not _wants_out_of_reservation("what is your cancellation policy")
    assert not _wants_out_of_reservation("a table for four")
    # Genuine exits still work.
    assert _wants_out_of_reservation("I need to cancel")
    assert _wants_out_of_reservation("never mind")
    assert _wants_out_of_reservation("actually I want to place an order instead")


async def test_a_correction_during_confirmation_is_not_read_as_a_yes(
    db_session, vector_db, embedding_provider, restaurant
):
    """
    "yes, but can you make it 8 instead" contains "yes". Reading only
    that booked the table at the time the caller was in the middle of
    correcting — and wrote a real reservation row while doing it.

    _handle_confirm_transfer already guarded against a long reply that
    merely starts with yes; this branch, the one that writes to the
    database, did not.
    """
    extraction_responses = iter(
        [
            json.dumps({"customer_name": "Jane Smith", "customer_phone": "555-123-4567",
                        "reservation_date": FUTURE_DATE, "reservation_time": "19:00",
                        "party_size": 4, "special_notes": None}),
            # The correction: 7pm becomes 8pm.
            json.dumps({"customer_name": None, "customer_phone": None,
                        "reservation_date": None, "reservation_time": "20:00",
                        "party_size": None, "special_notes": None}),
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

    await engine.handle_turn(context, "Table for four Friday at 7, Jane Smith, 555-123-4567")
    assert context.state == ConversationState.RESERVATION_CONFIRMING

    result = await engine.handle_turn(
        context, "yes, but can you make it 8 instead", call_sid="CA_correction"
    )

    # Nothing booked on the turn that changed a detail.
    assert result.reservation is None
    # The new time is read back for confirmation, not silently applied.
    assert context.state == ConversationState.RESERVATION_CONFIRMING
    assert "8" in result.response_text
    assert context.reservation_draft.reservation_time == "20:00"

    from sqlalchemy import select

    from app.db.models import Reservation

    rows = await db_session.execute(
        select(Reservation).where(Reservation.restaurant_id == restaurant.id)
    )
    assert rows.scalars().all() == []


async def test_a_wordy_yes_that_changes_nothing_still_books(
    db_session, vector_db, embedding_provider, restaurant
):
    """The guard above must not make a polite caller repeat themselves:
    a long reply that moves no field is just a wordy yes."""
    extraction_responses = iter(
        [
            json.dumps({"customer_name": "Jane Smith", "customer_phone": "555-123-4567",
                        "reservation_date": FUTURE_DATE, "reservation_time": "19:00",
                        "party_size": 4, "special_notes": None}),
            # Nothing new in "yes that all sounds right, thank you".
            json.dumps({"customer_name": None, "customer_phone": None,
                        "reservation_date": None, "reservation_time": None,
                        "party_size": None, "special_notes": None}),
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

    await engine.handle_turn(context, "Table for four Friday at 7, Jane Smith, 555-123-4567")
    result = await engine.handle_turn(
        context, "yes that all sounds right, thank you very much", call_sid="CA_wordy"
    )

    assert result.reservation is not None
    assert result.reservation.customer_name == "Jane Smith"


# ----------------------------------------------------------------------
# A second restaurant on the same deployment
#
# The engine must behave identically for a business whose content,
# cuisine, timezone and settings are nothing like the first one's.
# Onboarding a client is a data change, so a data change must not be
# able to alter the conversation logic — or to leak one restaurant's
# answers into another's call.
# ----------------------------------------------------------------------


async def _second_restaurant(db_session):
    from app.db.models import Restaurant as RestaurantModel
    from app.db.models import RestaurantHours

    r = RestaurantModel(
        name="Trattoria Nova",
        timezone="Europe/Rome",              # different timezone
        phone_number="+390612345678",
        email="owner@trattorianova.example",
        transfer_number="+390698765432",
        stt_vocabulary="carbonara, amatriciana, arancini, burrata",
        takes_reservations=True,
        is_active=True,
    )
    db_session.add(r)
    await db_session.flush()
    for day in range(7):
        db_session.add(
            RestaurantHours(
                restaurant_id=r.id, day_of_week=day, opening_time="12:00", closing_time="23:30"
            )
        )
    await db_session.commit()
    await db_session.refresh(r)
    return r


async def test_a_second_restaurants_call_uses_its_own_knowledge_only(
    db_session, vector_db, embedding_provider, restaurant
):
    other = await _second_restaurant(db_session)

    await knowledge_service.create_document(
        db_session, vector_db, embedding_provider, restaurant.id, "Seating",
        "Do you have outdoor seating? Yes, we have outdoor seating on our patio.", "policy", None,
    )
    await knowledge_service.create_document(
        db_session, vector_db, embedding_provider, other.id, "Seating",
        "Do you have outdoor seating? Yes, we have outdoor seating in our courtyard.", "policy", None,
    )
    await db_session.commit()

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
            (contains("using ONLY the information below"),
             lambda prompt: "courtyard" if "courtyard" in prompt else "WRONG RESTAURANT"),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, other)
    context = ConversationContext(restaurant_id=other.id)

    result = await engine.handle_turn(context, "Do you have outdoor seating?")

    # Grounded in its OWN document; the other restaurant's patio never
    # reaches the prompt.
    assert "courtyard" in result.response_text
    faq_prompts = [c for c in llm.calls if "using ONLY the information below" in c]
    assert faq_prompts and "patio" not in faq_prompts[0]


async def test_the_yes_no_fixes_hold_for_a_second_restaurant(
    db_session, vector_db, embedding_provider, restaurant
):
    """The confirm/deny reading is a property of the conversation logic,
    not of whose menu is loaded — so it must behave the same here."""
    other = await _second_restaurant(db_session)

    extraction_responses = iter(
        [
            json.dumps({"customer_name": "Marco Rossi", "customer_phone": "555-987-6543",
                        "reservation_date": FUTURE_DATE, "reservation_time": "19:00",
                        "party_size": 2, "special_notes": None}),
        ]
    )
    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "RESERVATION"),
            (contains("Extract reservation details"), lambda _p: next(extraction_responses)),
        ]
    )
    engine = _engine(llm, embedding_provider, vector_db, db_session, other)
    context = ConversationContext(restaurant_id=other.id)

    await engine.handle_turn(context, "Table for two Friday at 7, Marco Rossi, 555-987-6543")
    assert context.state == ConversationState.RESERVATION_CONFIRMING

    # The refusal that used to book a table, on this restaurant too.
    result = await engine.handle_turn(context, "no, please don't", call_sid="CA_other")

    assert result.reservation is None
    assert context.state == ConversationState.RESERVATION_COLLECTING

    from sqlalchemy import select

    from app.db.models import Reservation

    rows = await db_session.execute(
        select(Reservation).where(Reservation.restaurant_id == other.id)
    )
    assert rows.scalars().all() == []
