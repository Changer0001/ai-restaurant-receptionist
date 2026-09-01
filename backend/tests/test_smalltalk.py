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
    reply = reply_to("Okay.", _RESTAURANT)
    assert "sorry" not in reply.lower()
    assert "anything else" in reply.lower()


def test_farewell_reply_closes_warmly_without_asking_another_question():
    reply = reply_to("Okay that's all, bye", _RESTAURANT)
    assert "anything else" not in reply.lower()
    assert "thank" in reply.lower() or "care" in reply.lower() or "day" in reply.lower()
