"""
Small Talk Handling

The parts of a phone call that aren't requests: "okay", "thanks",
"that's all", "what's your name?". They carry no information to look up,
but how they're handled is most of what makes a line feel human.

Answered from here rather than through the LLM, for two reasons. They're
closed-ended — there is no lookup to do and nothing to get wrong — and
every LLM round trip is a second of silence on a call that already
spends 5-10 of them per turn. A canned "you're welcome" that arrives
instantly reads far more human than a generated one that lands three
seconds later.

Real calls produced both failure modes this replaces: "Okay." was
classified UNCLEAR and answered with "I'm sorry, could you tell me a bit
more about what you need?", and "What was your name?" was classified as
a request for a human and transferred the caller to the restaurant.
"""

from typing import Optional

from app.conversation.phrasing import pick

_THANKS_WORDS = ("thank", "thanks", "appreciate")
# "hang up" and friends are here because a real caller said "let's hang
# up" and then "okay, just, I don't want to talk to you anymore, just
# hang up" — and was answered both times as though they'd asked
# something. Being unable to end a call you started is the single most
# trapped a caller can feel.
_GOODBYE_WORDS = (
    "bye",
    "goodbye",
    "good night",
    "have a good",
    "take care",
    "hang up",
    "end the call",
    "i'm done",
    "im done",
)
_DONE_PHRASES = ("that's all", "thats all", "that's it", "thats it", "nothing else", "no that's")
_IDENTITY_PHRASES = (
    "your name",
    "who am i speaking",
    "who is this",
    "who's this",
    "are you a robot",
    "are you a real person",
    "are you human",
    "am i talking to a robot",
    "is this a machine",
    "are you an ai",
)

# Several phrasings each, and never the same one twice running (see
# app/conversation/phrasing.py): a receptionist who answers every
# "thanks" with the identical sentence is the tell that gives an
# automated line away fastest, and it costs nothing to vary.
_THANKS_REPLIES = (
    "You're very welcome. Anything else I can help you with?",
    "Happy to help. Was there anything else?",
    "Of course. Anything else you need?",
)
_ACKNOWLEDGEMENT_REPLIES = (
    "Sure thing. Anything else I can help with?",
    "Of course. Anything else you'd like to know?",
    "Great. Is there anything else?",
)
_GOODBYE_REPLIES = (
    "Thanks for calling, have a good one!",
    "Thank you for calling. Take care!",
    "Have a great day, thanks for calling!",
)

# Answering "how are you?" is the most basic courtesy there is, and
# skipping it is glaring. These answer the question and hand the call
# back — a caller who opens with a pleasantry still has a reason for
# ringing.
_GREETING_REPLIES = (
    "I'm doing well, thanks for asking! What can I get for you?",
    "Doing great, thank you! How can I help?",
    "All good here, thanks! What can I do for you?",
)

# Used instead of the "anything else?" lines before anything has
# actually been answered. There is no "else" yet.
_OPENING_REPLIES = (
    "Of course. What can I help you with?",
    "Sure. What can I get for you?",
    "Happy to help. What did you need?",
)

_GREETING_STARTS = ("hi", "hello", "hey", "good morning", "good afternoon", "good evening")
_HOW_ARE_YOU_PHRASES = (
    "how are you",
    "how're you",
    "how are things",
    "how's it going",
    "hows it going",
    "how you doing",
)

# A "done" phrase only closes a call when it's most of what was said —
# see is_farewell.
_SHORT_CLOSING_WORDS = 6


def is_identity_question(message: str) -> bool:
    """
    "What's your name?", "am I talking to a robot?" — a question about
    whoever picked up the phone, not a request to be handed to someone
    else. Classifying it as "caller wants a human" transfers people out
    of a conversation they were happy to be in.
    """
    lowered = message.lower()
    return any(phrase in lowered for phrase in _IDENTITY_PHRASES)


_OUT_OF_SCOPE_REPLIES = (
    "That one's outside what I can help with, I'm afraid — I only know about things here at the restaurant. Anything I can help with on that side?",
    "I couldn't tell you that one, sorry. I can help with anything about the restaurant itself though — what were you after?",
    "That's a bit beyond me, I'm afraid. I'm happy to help with anything about us though.",
)


def out_of_scope_reply(avoid: Optional[str] = None) -> str:
    """
    For a question a restaurant's phone line simply can't answer — the
    weather, the traffic, general knowledge.

    A real caller asked about the weather and about traffic from
    downtown. Both cycled through "I'm sorry, could you tell you me a
    bit more about what you need?" and then pulled seating and parking
    documents to answer from. Saying plainly that it's not something we
    can help with is both more honest and far more human than either.
    """
    return pick(_OUT_OF_SCOPE_REPLIES, avoid)


def identity_answer(restaurant_name: str) -> str:
    """
    Who the caller is speaking to, as a statement — no trailing question.

    Kept separate from reply_to so it can be used mid-flow (e.g. while a
    transfer offer is pending) without asking the caller a second
    question on top of the one already waiting for them.
    """
    return f"I'm the assistant here at {restaurant_name}."


def is_farewell(message: str) -> bool:
    """
    Whether the caller is wrapping the call up, not just acknowledging.

    A "done" phrase only ends a call when it's most of what was said.
    "That's all we're going to do next week" contains "that's all" but is
    plainly not a goodbye — a real call hit exactly that and got sent off
    with "thanks for calling, have a good one!" mid-conversation.
    """
    lowered = message.lower()
    if any(word in lowered for word in _GOODBYE_WORDS):
        return True
    return len(lowered.split()) <= _SHORT_CLOSING_WORDS and any(
        phrase in lowered for phrase in _DONE_PHRASES
    )


def is_greeting(message: str) -> bool:
    """"Hi", "good morning", "how are you doing today?" — an opening, not a request."""
    lowered = message.lower().strip(" .!?")
    if any(lowered.startswith(word) for word in _GREETING_STARTS):
        return True
    return any(phrase in lowered for phrase in _HOW_ARE_YOU_PHRASES)


def reply_to(
    message: str,
    restaurant_name: str,
    avoid: Optional[str] = None,
    caller_name: Optional[str] = None,
    already_helped: bool = False,
) -> str:
    """
    A natural reply to a greeting, acknowledgement, thanks, farewell or
    identity question.

    already_helped says whether anything has actually been answered yet
    on this call. It decides between "anything else?" and "what can I
    help you with?" — offering "anything else" before doing anything at
    all is nonsense, and it's what a caller heard when they opened with
    "hello, how are you doing today?" and got "Sure thing. Anything else
    I can help with?"
    """
    lowered = message.lower()

    if is_identity_question(message):
        # Warm, honest, and moves on — this is an aside in the caller's
        # actual call, not a topic to dwell on.
        return f"{identity_answer(restaurant_name)} What can I help you with?"

    if is_farewell(message):
        goodbye = pick(_GOODBYE_REPLIES, avoid)
        # Using a regular's name as they hang up is the kind of small
        # thing that makes a place feel like it knows you.
        return f"Thanks {caller_name}, have a great day!" if caller_name else goodbye

    # Before thanks: "hi, thanks for picking up" is a greeting, and
    # someone asking how your day is going deserves an answer, not a
    # "you're welcome".
    if is_greeting(message):
        return pick(_GREETING_REPLIES, avoid)

    if any(word in lowered for word in _THANKS_WORDS):
        return pick(_THANKS_REPLIES, avoid)

    return pick(_ACKNOWLEDGEMENT_REPLIES if already_helped else _OPENING_REPLIES, avoid)
