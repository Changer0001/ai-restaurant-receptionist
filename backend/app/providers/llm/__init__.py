"""LLM Provider Package"""

from typing import Optional

from app.providers.llm.base import LLMProvider
from app.providers.llm.ollama_provider import OllamaLLMProvider

__all__ = ["LLMProvider", "OllamaLLMProvider", "get_llm_provider"]

_llm_provider: Optional[LLMProvider] = None


async def get_llm_provider() -> LLMProvider:
    """Get the (lazily-initialized, process-wide) LLM provider.

    A FastAPI dependency — override with `app.dependency_overrides` in
    tests to avoid requiring a live Ollama server.
    """
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = OllamaLLMProvider()
    return _llm_provider
