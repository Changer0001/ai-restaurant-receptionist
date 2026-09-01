"""
Tests for app.conversation.phrasing and the varied lines built on it.

Hearing the identical sentence twice running is the fastest tell that a
caller is talking to a machine. Real calls produced exactly that: the
same fallback line twice in a row, and "anything else I can help with?"
after every acknowledgement.
"""

from app.conversation.phrasing import pick
from app.conversation.smalltalk import reply_to

_OPTIONS = ("first", "second", "third")


def test_the_line_just_used_is_never_picked_again():
    for _ in range(50):
        assert pick(_OPTIONS, avoid="first") != "first"


def test_a_single_option_still_produces_a_line():
    """Never failing to have something to say matters more than variety."""
    assert pick(("only one",), avoid="only one") == "only one"


def test_no_avoid_still_picks_something_valid():
    assert pick(_OPTIONS) in _OPTIONS


def test_repeated_acknowledgements_do_not_repeat_the_same_reply():
    """
    A caller saying "okay" twice in a row must not hear the identical
    sentence back both times.
    """
    first = reply_to("Okay.", "Mal Al Sham")
    second = reply_to("Okay.", "Mal Al Sham", avoid=first)
    assert second != first


def test_a_known_caller_is_said_goodbye_to_by_name():
    reply = reply_to("Okay, thanks, bye", "Mal Al Sham", caller_name="Mike")
    assert "Mike" in reply


def test_an_unknown_caller_still_gets_a_warm_goodbye():
    reply = reply_to("Okay, thanks, bye", "Mal Al Sham")
    assert "None" not in reply
    assert len(reply) > 0
