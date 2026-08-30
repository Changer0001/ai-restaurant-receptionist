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

from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider

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

    async def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int | None = None) -> str:
        self.calls.append(prompt)
        for predicate, response in self._rules:
            if predicate(prompt):
                return response(prompt) if callable(response) else response
        return self._default

    async def chat(
        self, messages: list[dict[str, str]], temperature: float = 0.7, max_tokens: int | None = None
    ) -> str:
        return await self.generate(messages[-1]["content"], temperature, max_tokens)

    async def health_check(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["scripted-fake"]
