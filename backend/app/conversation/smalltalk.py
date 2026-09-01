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

import random

_THANKS_WORDS = ("thank", "thanks", "appreciate")
_GOODBYE_WORDS = ("bye", "goodbye", "good night", "have a good", "take care")
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

# Several phrasings each, chosen at random: a receptionist who answers
# every "thanks" with the identical sentence is the tell that gives an
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


def out_of_scope_reply() -> str:
    """
    For a question a restaurant's phone line simply can't answer — the
    weather, the traffic, general knowledge.

    A real caller asked about the weather and about traffic from
    downtown. Both cycled through "I'm sorry, could you tell you me a
    bit more about what you need?" and then pulled seating and parking
    documents to answer from. Saying plainly that it's not something we
    can help with is both more honest and far more human than either.
    """
    return random.choice(_OUT_OF_SCOPE_REPLIES)


def identity_answer(restaurant_name: str) -> str:
    """
    Who the caller is speaking to, as a statement — no trailing question.

    Kept separate from reply_to so it can be used mid-flow (e.g. while a
    transfer offer is pending) without asking the caller a second
    question on top of the one already waiting for them.
    """
    return f"I'm the assistant here at {restaurant_name}."


def is_farewell(message: str) -> bool:
    """Whether the caller is wrapping the call up, not just acknowledging."""
    lowered = message.lower()
    return any(word in lowered for word in _GOODBYE_WORDS) or any(
        phrase in lowered for phrase in _DONE_PHRASES
    )


def reply_to(message: str, restaurant_name: str) -> str:
    """A natural reply to an acknowledgement, thanks, farewell or identity question."""
    lowered = message.lower()

    if is_identity_question(message):
        # Warm, honest, and moves on — this is an aside in the caller's
        # actual call, not a topic to dwell on.
        return f"{identity_answer(restaurant_name)} What can I help you with?"

    if is_farewell(message):
        return random.choice(_GOODBYE_REPLIES)

    if any(word in lowered for word in _THANKS_WORDS):
        return random.choice(_THANKS_REPLIES)

    return random.choice(_ACKNOWLEDGEMENT_REPLIES)
