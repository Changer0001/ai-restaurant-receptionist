"""
Groq LLM Provider

Hosted inference via Groq's OpenAI-compatible chat completions API
(https://console.groq.com/docs/api-reference#chat-create). Exists
alongside OllamaLLMProvider so a deployment can choose fully local
(private, needs a GPU for good phone-call latency) or hosted (fast even
on CPU hardware, free tier available) per LLM_PROVIDER — see
app/core/config.py.
"""

import logging
from typing import Dict, List, Optional

import httpx

from app.core.config import settings
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_API_BASE = "https://api.groq.com/openai/v1"


class GroqLLMProvider(LLMProvider):
    """
    Groq-based LLM provider for hosted inference.

    generate() has no native single-prompt completion endpoint to call
    the way Ollama's /api/generate does — Groq (like OpenAI) only
    exposes chat completions — so it wraps the prompt as a single user
    message and delegates to chat(), matching how callers already use
    this interface (every caller in app/conversation/ already only
    calls generate() with a fully-rendered prompt string, never a
    multi-turn messages list).
    """

    def __init__(
        self,
        api_key: str = settings.GROQ_API_KEY,
        model: str = settings.GROQ_MODEL,
        timeout: int = settings.GROQ_REQUEST_TIMEOUT,
    ):
        if not api_key:
            # Fails fast at construction rather than on the first live
            # call — a missing key is a deployment misconfiguration,
            # not a transient/retryable error.
            raise ValueError(
                "GROQ_API_KEY is not set. Required when LLM_PROVIDER=groq — "
                "get one at https://console.groq.com/keys"
            )
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            base_url=_API_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text from a prompt (see class docstring: delegates to chat())."""
        return await self.chat(
            [{"role": "user", "content": prompt}], temperature=temperature, max_tokens=max_tokens
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Chat completion."""
        body: Dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        try:
            response = await self.client.post("/chat/completions", json=body)
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"]).strip()
        except httpx.HTTPError as e:
            logger.error(f"Groq chat error: {e}")
            raise
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected Groq response shape: {e}")
            raise

    async def health_check(self) -> bool:
        """Check if Groq is accessible with the configured API key."""
        try:
            response = await self.client.get("/models")
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Groq health check failed: {e}")
            return False

    async def list_models(self) -> List[str]:
        """List available models."""
        try:
            response = await self.client.get("/models")
            response.raise_for_status()
            data = response.json()
            return [model["id"] for model in data.get("data", [])]
        except Exception as e:
            logger.error(f"Failed to list Groq models: {e}")
            return []

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
