"""
What the caller hears when something behind the scenes breaks.

A phone call has no error page. If Groq is down, or Ollama is not
running, or the vector store is unreachable, the caller is still on the
line — and the worst possible response is the one that costs nothing to
implement: silence, until they give up and hang up.

Every scenario here asserts two things: the caller hears something, and
what they hear does not leak the failure.
"""

import logging

import numpy as np

from app.db.models import CallOutcomeEnum
from app.services import call_service
from app.voice.session import CallSession
from tests.fakes import FakeTTSProvider, ScriptedLLMProvider, ScriptedSTTProvider


def _fake_audio_frame():
    return np.ones(1600, dtype=np.int16) * 5000


class _RecordingSender:
    def __init__(self):
        self.sent: list[bytes] = []

    async def __call__(self, mulaw_bytes: bytes) -> None:
        self.sent.append(mulaw_bytes)


class _BrokenLLM(ScriptedLLMProvider):
    """Stands in for a provider outage — Groq 503, a timeout, a DNS failure."""

    def __init__(self, message="Groq is unreachable"):
        super().__init__([])
        self.message = message

    async def generate(self, prompt: str, **kwargs) -> str:
        raise ConnectionError(self.message)


async def _session(db_session, restaurant, vector_db, embedding_provider, llm, stt):
    call = await call_service.create_call(
        db_session, restaurant.id, "CA_fail", "+15551234567", restaurant.phone_number
    )
    sender = _RecordingSender()
    session = CallSession(
        db_session, call, restaurant, stt, FakeTTSProvider(), llm,
        embedding_provider, vector_db, sender,
    )
    session.turn_detector.pop_utterance = lambda: _fake_audio_frame()
    return session, sender


async def test_an_llm_outage_does_not_leave_the_caller_in_silence(
    db_session, restaurant, vector_db, embedding_provider, caplog
):
    """
    The engine has no error handling of its own, so a provider raising
    propagated all the way to the turn task, which logged it and
    returned. The caller heard nothing at all and eventually hung up.
    """
    stt = ScriptedSTTProvider([("do you have parking?", 0.9)])
    session, sender = await _session(
        db_session, restaurant, vector_db, embedding_provider, _BrokenLLM(), stt
    )

    with caplog.at_level(logging.INFO):
        await session._process_utterance()

    assert sender.sent, "the caller heard nothing"

    spoken = " ".join(t.content for t in session.context.history if t.role == "assistant")
    assert spoken, "nothing was recorded as said"
    # And it must not read the stack trace out to them.
    for leak in ("Groq", "ConnectionError", "Traceback", "unreachable", "None"):
        assert leak not in spoken, f"internal detail {leak!r} leaked to the caller"


async def test_a_repeatedly_broken_backend_hands_the_caller_to_a_person(
    db_session, restaurant, vector_db, embedding_provider
):
    """
    Apologising forever is its own failure. If the backend is genuinely
    down, the caller should reach someone who can actually help.
    """
    stt = ScriptedSTTProvider([("do you have parking?", 0.9)] * 5)
    session, _sender = await _session(
        db_session, restaurant, vector_db, embedding_provider, _BrokenLLM(), stt
    )

    for _ in range(3):
        await session._process_utterance()

    assert session.should_close is True
    assert session.final_outcome == CallOutcomeEnum.HUMAN_ESCALATION


async def test_a_working_turn_clears_the_failure_streak(
    db_session, restaurant, vector_db, embedding_provider
):
    """One blip mid-call must not push a later one straight to a human."""
    from tests.fakes import contains

    class _FlakyLLM(ScriptedLLMProvider):
        def __init__(self):
            super().__init__(
                [
                    (contains("decide if it needs to be handed off"), "NO"),
                    (contains("Respond with exactly one of these labels"), "FAQ"),
                ]
            )
            self.calls_made = 0

        async def generate(self, prompt: str, **kwargs) -> str:
            self.calls_made += 1
            if self.calls_made <= 2:  # the first turn's two classifier calls
                raise ConnectionError("blip")
            return await super().generate(prompt, **kwargs)

    stt = ScriptedSTTProvider([("do you have parking?", 0.9)] * 4)
    session, _sender = await _session(
        db_session, restaurant, vector_db, embedding_provider, _FlakyLLM(), stt
    )

    await session._process_utterance()   # fails
    await session._process_utterance()   # recovers
    await session._process_utterance()   # would be strike 3 if it counted

    assert session.should_close is False
