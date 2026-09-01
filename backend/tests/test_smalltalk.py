"""Tests for app.conversation.smalltalk."""

from app.conversation.smalltalk import is_farewell, is_identity_question, reply_to

_RESTAURANT = "Mal Al Sham"


def test_identity_questions_are_recognised():
    """
    A real call classified "What was your name?" as a request for a
    human and transferred the caller. Asking who picked up the phone is
    not asking to be handed to someone else.
    """
    assert is_identity_question("What was your name?")
    assert is_identity_question("Sorry, who is this?")
    assert is_identity_question("Am I talking to a robot?")
    assert is_identity_question("Are you a real person?")
    assert not is_identity_question("Can I speak to a manager?")
    assert not is_identity_question("Do you have parking?")


def test_identity_reply_names_the_restaurant_and_moves_on():
    reply = reply_to("What's your name?", _RESTAURANT)
    assert _RESTAURANT in reply
    # Answers, then hands the call back to the caller rather than
    # dwelling on what it is.
    assert "help" in reply.lower()


def test_farewells_are_recognised():
    assert is_farewell("Okay, thanks, bye")
    assert is_farewell("No, that's all")
    assert is_farewell("That's it, thank you")
    assert not is_farewell("Okay")
    assert not is_farewell("Thanks")


def test_thanks_gets_a_welcome_and_an_opening_to_continue():
    reply = reply_to("Thank you so much", _RESTAURANT)
    assert "welcome" in reply.lower() or "happy to help" in reply.lower() or "course" in reply.lower()
    assert "anything else" in reply.lower()


def test_bare_acknowledgement_does_not_ask_the_caller_to_repeat_themselves():
    """
    "Okay." used to be classified UNCLEAR and answered with "I'm sorry,
    could you tell me a bit more about what you need?" — which reads as
    the line not having understood a perfectly normal acknowledgement.
    """
    reply = reply_to("Okay.", _RESTAURANT, already_helped=True)
    assert "sorry" not in reply.lower()
    assert "anything else" in reply.lower()


def test_nothing_is_offered_as_anything_else_before_anything_has_happened():
    """
    A caller opening the call with a pleasantry got "Sure thing. Anything
    else I can help with?" — there was no "else"; nothing had been asked
    or answered yet.
    """
    reply = reply_to("Okay.", _RESTAURANT, already_helped=False)
    assert "anything else" not in reply.lower()
    assert "?" in reply


def test_asking_how_the_day_is_going_gets_an_actual_answer():
    """
    "Hello, how are you doing today?" was answered with "Sure thing.
    Anything else I can help with?" — the question was ignored, and an
    offer was made about work that had not happened.
    """
    reply = reply_to("Hello, how are you doing today?", _RESTAURANT)
    assert "anything else" not in reply.lower()
    # Answers the question, then hands the call back.
    assert any(word in reply.lower() for word in ("well", "great", "good"))
    assert "?" in reply


def test_greetings_are_recognised():
    from app.conversation.smalltalk import is_greeting

    assert is_greeting("Hi there")
    assert is_greeting("Good morning")
    assert is_greeting("Hello, how are you doing today?")
    assert is_greeting("How's it going?")
    assert not is_greeting("Do you have parking?")
    assert not is_greeting("Thanks very much")


def test_a_done_phrase_mid_sentence_does_not_end_the_call():
    """
    "That's all we're going to do next week" contains "that's all" but is
    not a goodbye — a real caller said it and was sent off with "thanks
    for calling, have a good one!" in the middle of the conversation.
    """
    from app.conversation.smalltalk import is_farewell

    assert not is_farewell("That's all we're going to do next week")
    assert is_farewell("No, that's all")
    assert is_farewell("That's it, thanks")
    # An explicit goodbye still ends the call at any length.
    assert is_farewell("Okay well I think we are done here, goodbye")


def test_farewell_reply_closes_warmly_without_asking_another_question():
    reply = reply_to("Okay that's all, bye", _RESTAURANT)
    assert "anything else" not in reply.lower()
    assert "thank" in reply.lower() or "care" in reply.lower() or "day" in reply.lower()


def test_identity_answer_is_a_statement_not_another_question():
    """
    Used mid-flow (e.g. while a transfer offer is pending), so it must
    not ask the caller a second question on top of the one already
    waiting for them.
    """
    from app.conversation.smalltalk import identity_answer

    answer = identity_answer(_RESTAURANT)
    assert _RESTAURANT in answer
    assert "?" not in answer


def test_out_of_scope_reply_does_not_ask_the_caller_to_repeat_themselves():
    from app.conversation.smalltalk import out_of_scope_reply

    reply = out_of_scope_reply()
    assert "tell me a bit more" not in reply.lower()
    assert len(reply) > 0
