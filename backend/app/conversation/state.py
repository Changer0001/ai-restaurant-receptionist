"""
Conversation State

Explicit state, not an LLM asked to "remember" the call. The state
machine (see engine.py) transitions between these states deterministically
based on classified intent and collected data — the LLM's job is natural
language understanding and generation *within* a state, never deciding
the state graph itself. See docs/architecture.md for why.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConversationState(str, Enum):
    """
    A caller is always in exactly one of these states.

    FAQ doesn't need its own "parked" state — it's a single-turn branch
    handled inline from IDENTIFY_INTENT, staying in IDENTIFY_INTENT
    afterward, ready for the next question. HUMAN (the caller
    explicitly asking for a person) is also immediate, straight to
    TRANSFER_TO_HUMAN — asking "would you like a human?" when they just
    said exactly that would be a redundant, irritating extra turn.
    Every other transfer trigger (ORDER; RESERVATION when
    FEATURE_RESERVATION_COLLECTION is off; sentiment-based escalation;
    repeated UNCLEAR) instead parks in CONFIRM_TRANSFER first: the
    engine offers a handoff rather than silently forcing one, the way a
    human agent would ask "would you like me to get someone for you?"
    rather than just transferring the call on their own judgment.
    """

    GREETING = "GREETING"
    IDENTIFY_INTENT = "IDENTIFY_INTENT"
    RESERVATION_COLLECTING = "RESERVATION_COLLECTING"
    RESERVATION_CONFIRMING = "RESERVATION_CONFIRMING"
    CONFIRM_TRANSFER = "CONFIRM_TRANSFER"
    TRANSFER_TO_HUMAN = "TRANSFER_TO_HUMAN"
    ENDED = "ENDED"


# Fields required before a reservation request can be submitted.
# special_notes is deliberately excluded — it's optional information.
REQUIRED_RESERVATION_FIELDS = (
    "customer_name",
    "customer_phone",
    "reservation_date",
    "reservation_time",
    "party_size",
)


@dataclass
class ReservationDraft:
    """Reservation details collected so far. All fields are None until filled."""

    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    reservation_date: Optional[str] = None  # YYYY-MM-DD
    reservation_time: Optional[str] = None  # HH:MM, 24-hour
    party_size: Optional[int] = None
    special_notes: Optional[str] = None

    def missing_fields(self) -> list[str]:
        return [f for f in REQUIRED_RESERVATION_FIELDS if getattr(self, f) is None]

    def is_complete(self) -> bool:
        return not self.missing_fields()


@dataclass
class Turn:
    role: str  # "caller" or "assistant"
    content: str


@dataclass
class ConversationContext:
    """
    Everything the engine needs to carry between turns of one call.

    Phase 5 will persist/restore this per call_sid (likely via Redis,
    given CallState is inherently short-lived and call-scoped — see
    docs/architecture.md's Redis section); for now it's an in-memory
    object the caller of ConversationEngine owns for the lifetime of one
    conversation (and tests construct directly).
    """

    restaurant_id: str
    state: ConversationState = ConversationState.GREETING
    history: list[Turn] = field(default_factory=list)
    reservation_draft: ReservationDraft = field(default_factory=ReservationDraft)
    transfer_reason: Optional[str] = None
    unclear_count: int = 0

    def add_turn(self, role: str, content: str) -> None:
        self.history.append(Turn(role=role, content=content))

    def history_text(self, max_turns: int = 10) -> str:
        """Recent conversation as plain text, for embedding into prompts
        that need context (intent classification, escalation review)."""
        recent = self.history[-max_turns:]
        if not recent:
            return "(nothing said yet)"
        return "\n".join(f"{t.role}: {t.content}" for t in recent)
