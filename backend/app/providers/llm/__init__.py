"""LLM Provider Package"""

import logging
from typing import Optional

from app.core.config import settings
from app.providers.llm.base import LLMProvider
from app.providers.llm.ollama_provider import OllamaLLMProvider

logger = logging.getLogger(__name__)

__all__ = ["LLMProvider", "OllamaLLMProvider", "get_llm_provider", "get_classifier_llm_provider"]

_llm_provider: Optional[LLMProvider] = None
_classifier_provider: Optional[LLMProvider] = None


async def get_llm_provider() -> LLMProvider:
    """
    Get the (lazily-initialized, process-wide) LLM provider, selected by
    LLM_PROVIDER ("ollama" or "groq"). A FastAPI dependency — override
    with `app.dependency_overrides` in tests to avoid requiring a live
    LLM backend.
    """
    global _llm_provider
    if _llm_provider is None:
        if settings.LLM_PROVIDER == "groq":
            from app.providers.llm.groq_provider import GroqLLMProvider

            _llm_provider = GroqLLMProvider()
        else:
            _llm_provider = OllamaLLMProvider()
        logger.info(f"LLM provider initialized: {settings.LLM_PROVIDER}")
    return _llm_provider


async def get_classifier_llm_provider() -> LLMProvider:
    """
    The provider used for the per-turn classification calls (escalation
    check, intent). Same interface, potentially a smaller/faster model —
    see GROQ_CLASSIFIER_MODEL.

    Falls back to the main provider for Ollama, where there is one local
    model loaded and pointing these calls at a second one would mean
    loading and holding another model in memory for no gain.
    """
    global _classifier_provider
    if _classifier_provider is None:
        if settings.LLM_PROVIDER == "groq" and settings.GROQ_CLASSIFIER_MODEL:
            from app.providers.llm.groq_provider import GroqLLMProvider

            _classifier_provider = GroqLLMProvider(model=settings.GROQ_CLASSIFIER_MODEL)
            logger.info(f"Classifier LLM: {settings.GROQ_CLASSIFIER_MODEL}")
        else:
            _classifier_provider = await get_llm_provider()
    return _classifier_provider
