"""
Test doubles.

FakeEmbeddingProvider stands in for OllamaEmbeddingProvider in tests, so
the RAG test suite doesn't require a live Ollama server. It uses a
deterministic feature-hashing scheme (hash each word into one of a fixed
number of buckets, sum, L2-normalize) rather than a real embedding model
— it has no semantic understanding, but text that shares more words
does score more similar, which is enough to test the actual things this
suite cares about: tenant filtering, top_k limiting, and relevance-
threshold cutoffs. Production always uses OllamaEmbeddingProvider; this
is confined to tests/.
"""

import hashlib
from typing import Callable, Union

import numpy as np

from app.providers.email.base import EmailProvider
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.stt.base import STTProvider
from app.providers.telephony.base import TelephonyProvider
from app.providers.tts.base import TTSProvider

_DIMENSIONS = 32


class FakeEmbeddingProvider(EmbeddingProvider):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * _DIMENSIONS
        for word in text.lower().split():
            digest = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
            index = digest % _DIMENSIONS
            sign = 1.0 if (digest // _DIMENSIONS) % 2 == 0 else -1.0
            vector[index] += sign

        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    async def health_check(self) -> bool:
        return True


_Response = Union[str, Callable[[str], str]]
_Rule = tuple[Callable[[str], bool], _Response]


def contains(substring: str) -> Callable[[str], bool]:
    """A rule predicate: matches if `substring` appears in the rendered prompt."""
    return lambda prompt: substring in prompt


class ScriptedLLMProvider(LLMProvider):
    """
    Stands in for OllamaLLMProvider in conversation-engine tests.

    Routes each generate() call against an ordered list of (predicate,
    response) rules, tested against the fully-rendered prompt text — the
    first matching rule wins. `response` may be a literal string, or a
    callable(prompt) -> str for replies that need to vary by call (e.g.
    reservation extraction returning different fields on each turn).
    Matching against stable, template-fixed instructional text (see
    `contains()`) rather than the whole prompt keeps rules independent of
    which variables happen to be interpolated into a given call.

    Every call is recorded in `.calls` for tests that want to assert
    which prompts were actually issued.
    """

    def __init__(self, rules: list[_Rule], default: str = "UNCLEAR"):
        self._rules = rules
        self._default = default
        self.calls: list[str] = []

    async def generate(
        self, prompt: str, temperature: float = 0.7, max_tokens: int | None = None
    ) -> str:
        self.calls.append(prompt)
        for predicate, response in self._rules:
            if predicate(prompt):
                return response(prompt) if callable(response) else response
        return self._default

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        return await self.generate(messages[-1]["content"], temperature, max_tokens)

    async def health_check(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["scripted-fake"]


class ScriptedSTTProvider(STTProvider):
    """
    Stands in for FasterWhisperSTTProvider in voice-pipeline tests —
    real speech recognition isn't the thing under test there (the fake
    embedding/LLM providers don't have real language understanding
    either); what matters is exercising the app logic that runs before
    and after transcription.

    Returns a queue of canned (text, confidence) results in order,
    regardless of the actual audio bytes passed in. Every call's audio is
    recorded in `.calls` for tests that want to assert transcribe() was
    (or wasn't) invoked, and with what; the vocabulary hint each call
    passed is recorded in `.vocabularies`, which is how tests check that
    a restaurant's own dish names reach speech recognition rather than
    another restaurant's.
    """

    def __init__(self, responses: list[tuple[str, float]]):
        self._responses = list(responses)
        self.calls: list[bytes] = []
        self.vocabularies: list[str | None] = []

    async def transcribe(self, audio: bytes, vocabulary: str | None = None) -> tuple[str, float]:
        self.calls.append(audio)
        self.vocabularies.append(vocabulary)
        if not self._responses:
            return "", 0.0
        return self._responses.pop(0)

    async def health_check(self) -> bool:
        return True


class FakeTTSProvider(TTSProvider):
    """
    Stands in for KokoroTTSProvider/PiperTTSProvider — generates a short
    deterministic PCM16 tone whose length scales with the input text
    (roughly modeling "longer sentences take longer to speak"), so
    duration-dependent logic (e.g. CallSession's no-barge-in playback
    gating) has a real, non-trivial value to compute against instead of
    an empty or fixed-length stub.
    """

    SAMPLE_RATE = 16000
    _MS_PER_CHARACTER = 60  # a rough, deliberately simple speech-rate stand-in

    async def synthesize(self, text: str, language: str = "en") -> tuple[bytes, int]:
        duration_s = max(len(text), 1) * self._MS_PER_CHARACTER / 1000
        num_samples = int(self.SAMPLE_RATE * duration_s)
        t = np.linspace(0, duration_s, num_samples, endpoint=False)
        tone = (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16)
        return tone.tobytes(), self.SAMPLE_RATE

    async def health_check(self) -> bool:
        return True


class FakeEmailProvider(EmailProvider):
    """
    Stands in for SMTPEmailProvider in notification-service tests.
    Records every successful send in `.sent`; recipients listed in
    `fail_for` raise instead, for exercising the worker's
    failure/retry/backoff handling without a real SMTP server.
    """

    def __init__(self, fail_for: set[str] | None = None):
        self.sent: list[tuple[str, str, str]] = []
        self._fail_for = fail_for or set()

    async def send_email(self, to: str, subject: str, body: str) -> None:
        if to in self._fail_for:
            raise RuntimeError(f"simulated SMTP failure for {to}")
        self.sent.append((to, subject, body))

    async def health_check(self) -> bool:
        return True


class FakeTelephonyProvider(TelephonyProvider):
    """
    Stands in for TwilioTelephonyProvider in notification-service tests
    — only send_sms is exercised there; the rest of the interface is
    stubbed just enough to satisfy the abstract base class.
    """

    def __init__(self, fail_for: set[str] | None = None):
        self.sent_sms: list[tuple[str, str, str]] = []
        self._fail_for = fail_for or set()

    async def validate_webhook_signature(self, signature: str, url: str, params) -> bool:
        return True

    async def transfer_call(self, call_sid: str, target_number: str, timeout: int = 30) -> dict:
        return {}

    async def end_call(self, call_sid: str) -> bool:
        return True

    async def send_digits(self, call_sid: str, digits: str) -> bool:
        return True

    async def record_call(self, call_sid: str) -> str:
        return call_sid

    async def health_check(self) -> bool:
        return True

    async def send_sms(self, to: str, from_: str, body: str) -> dict:
        if to in self._fail_for:
            raise RuntimeError(f"simulated Twilio failure for {to}")
        self.sent_sms.append((to, from_, body))
        return {"sid": "SMfake", "status": "queued"}
