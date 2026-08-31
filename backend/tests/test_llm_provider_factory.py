"""
Tests for app.providers.llm's get_llm_provider() factory.

Exercises the factory function directly rather than through the FastAPI
app/dependency-override machinery other provider tests use — there's no
existing app-level test for this factory to extend, and the thing under
test here is purely "does LLM_PROVIDER pick the right class," which
doesn't need a request/response cycle.
"""

import app.providers.llm as llm_package
from app.core.config import settings
from app.providers.llm import get_llm_provider
from app.providers.llm.ollama_provider import OllamaLLMProvider


def _reset_singleton():
    """The factory caches its provider in a module-level global — tests
    that flip LLM_PROVIDER need a fresh instance each time, not the one
    a previous test already cached."""
    llm_package._llm_provider = None


async def test_defaults_to_ollama():
    _reset_singleton()
    original = settings.LLM_PROVIDER
    settings.LLM_PROVIDER = "ollama"
    try:
        provider = await get_llm_provider()
        assert isinstance(provider, OllamaLLMProvider)
    finally:
        settings.LLM_PROVIDER = original
        _reset_singleton()


async def test_unrecognized_value_falls_back_to_ollama():
    """Matches get_tts_provider's own fallback behavior (app/providers/tts/__init__.py)
    — an unrecognized value degrades to the default rather than crashing."""
    _reset_singleton()
    original = settings.LLM_PROVIDER
    settings.LLM_PROVIDER = "some-typo"
    try:
        provider = await get_llm_provider()
        assert isinstance(provider, OllamaLLMProvider)
    finally:
        settings.LLM_PROVIDER = original
        _reset_singleton()


async def test_selects_groq(monkeypatch):
    """
    Deliberately doesn't construct a real GroqLLMProvider — its
    constructor's api_key default is bound to settings.GROQ_API_KEY at
    the module's first import, so mutating settings.GROQ_API_KEY here
    (after some earlier test may have already imported the module)
    wouldn't reliably reach it. GroqLLMProvider's own construction
    logic (including that default) is covered separately in
    test_groq_provider.py, which always passes api_key explicitly.
    This test isolates exactly one thing: does LLM_PROVIDER=groq make
    the factory reach for app.providers.llm.groq_provider.GroqLLMProvider.
    """
    import app.providers.llm.groq_provider as groq_module

    class FakeGroqProvider:
        pass

    monkeypatch.setattr(groq_module, "GroqLLMProvider", FakeGroqProvider)

    _reset_singleton()
    original_provider = settings.LLM_PROVIDER
    settings.LLM_PROVIDER = "groq"
    try:
        provider = await get_llm_provider()
        assert isinstance(provider, FakeGroqProvider)
    finally:
        settings.LLM_PROVIDER = original_provider
        _reset_singleton()


async def test_caches_the_instance_across_calls():
    _reset_singleton()
    original = settings.LLM_PROVIDER
    settings.LLM_PROVIDER = "ollama"
    try:
        first = await get_llm_provider()
        second = await get_llm_provider()
        assert first is second
    finally:
        settings.LLM_PROVIDER = original
        _reset_singleton()
