"""
Ollama LLM Provider

Local inference via Ollama (https://ollama.ai)
"""

import logging
from typing import Dict, List, Optional

import httpx

from app.core.config import settings
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OllamaLLMProvider(LLMProvider):
    """
    Ollama-based LLM provider for local inference.

    Supports Qwen 3 8B and other Ollama models.
    """

    def __init__(
        self,
        base_url: str = settings.OLLAMA_BASE_URL,
        model: str = settings.OLLAMA_MODEL,
        timeout: int = settings.OLLAMA_REQUEST_TIMEOUT,
    ):
        """Initialize Ollama provider."""
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text from a prompt."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()
        except httpx.HTTPError as e:
            logger.error(f"Ollama generate error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in Ollama generate: {e}")
            raise

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Chat completion."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            # Extract content from the last message
            if "message" in data and "content" in data["message"]:
                return str(data["message"]["content"]).strip()
            return ""
        except httpx.HTTPError as e:
            logger.error(f"Ollama chat error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in Ollama chat: {e}")
            raise

    async def health_check(self) -> bool:
        """Check if Ollama is accessible."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def list_models(self) -> List[str]:
        """List available models in Ollama."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = [model["name"] for model in data.get("models", [])]
            return models
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
            return []

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
