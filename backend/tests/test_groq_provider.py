"""Tests for app.providers.llm.groq_provider.GroqLLMProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.llm.groq_provider import GroqLLMProvider


def test_missing_api_key_raises():
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqLLMProvider(api_key="")


def _fake_response(json_body: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    response.raise_for_status = MagicMock()
    return response


async def test_generate_delegates_to_chat_as_a_single_user_message():
    provider = GroqLLMProvider(api_key="test-key", model="test-model")
    captured = {}

    async def fake_post(url, json):
        captured["url"] = url
        captured["json"] = json
        return _fake_response({"choices": [{"message": {"content": "hello"}}]})

    with patch.object(provider.client, "post", fake_post):
        result = await provider.generate("say hi", temperature=0.0)

    assert result == "hello"
    assert captured["url"] == "/chat/completions"
    assert captured["json"]["messages"] == [{"role": "user", "content": "say hi"}]
    assert captured["json"]["temperature"] == 0.0
    assert "max_tokens" not in captured["json"]  # omitted, not sent as null


async def test_chat_includes_max_tokens_when_given():
    provider = GroqLLMProvider(api_key="test-key", model="test-model")
    captured = {}

    async def fake_post(url, json):
        captured["json"] = json
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    with patch.object(provider.client, "post", fake_post):
        await provider.chat([{"role": "user", "content": "hi"}], max_tokens=50)

    assert captured["json"]["max_tokens"] == 50


async def test_chat_raises_on_http_error():
    provider = GroqLLMProvider(api_key="test-key", model="test-model")

    async def fake_post(url, json):
        raise httpx.HTTPStatusError("bad", request=MagicMock(), response=MagicMock())

    with patch.object(provider.client, "post", fake_post):
        with pytest.raises(httpx.HTTPStatusError):
            await provider.chat([{"role": "user", "content": "hi"}])


async def test_health_check_true_on_success():
    provider = GroqLLMProvider(api_key="test-key", model="test-model")
    provider.client.get = AsyncMock(return_value=_fake_response({}))
    assert await provider.health_check() is True


async def test_health_check_false_on_failure():
    provider = GroqLLMProvider(api_key="test-key", model="test-model")
    provider.client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    assert await provider.health_check() is False


async def test_list_models_parses_ids():
    provider = GroqLLMProvider(api_key="test-key", model="test-model")
    provider.client.get = AsyncMock(
        return_value=_fake_response({"data": [{"id": "openai/gpt-oss-120b"}, {"id": "openai/gpt-oss-20b"}]})
    )
    assert await provider.list_models() == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


async def test_list_models_returns_empty_on_failure():
    provider = GroqLLMProvider(api_key="test-key", model="test-model")
    provider.client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    assert await provider.list_models() == []
