"""Provider-agnostic LLM client abstraction for per-user review models.

Each user may configure their own provider/model/API key (settings page);
reviews resolve the right client at job time and fall back to the system
Groq default when no personal key is stored.

Design rules (feature brief):
- ``groq.py`` stays untouched — ``GroqLLMClient`` wraps it.
- ``resolve_llm_client`` NEVER raises: bad provider strings, decrypt
  failures, and any unexpected error fall back to the system Groq client.
- Every adapter raises ``httpx.HTTPStatusError`` (response attached) on
  HTTP >= 400 so the agents' 429/5xx backoff and the worker's error
  classifier keep working unchanged.
- API keys never appear in raised messages or log output (``_redact``).

Providers: Groq, OpenAI, Anthropic, Google Gemini, Ollama (local).
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import settings
from app.security.encryption import decrypt_api_key
from app.services.groq import GroqClient

logger = logging.getLogger(__name__)

# HTTP timeout for direct REST calls (matches groq.py / gemini.py).
LLM_HTTP_TIMEOUT = 120.0


class BaseLLMClient(ABC):
    """Unified completion interface all review agents call."""

    def __init__(self, api_key: str = "", model: str = "") -> None:
        self.api_key = api_key
        self.model = model
        self._usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    @abstractmethod
    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        """Send one prompt and return the provider's text response."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier stored on the finished review."""

    def total_usage(self) -> dict[str, int]:
        """Aggregate token usage across calls made through this instance."""

        return dict(self._usage)

    # -- shared helpers -------------------------------------------------

    def _record_usage(self, prompt_tokens: Any, completion_tokens: Any) -> None:
        """Accumulate token counts (tolerant of missing usage metadata)."""

        prompt = int(prompt_tokens or 0)
        completion = int(completion_tokens or 0)
        self._usage["prompt_tokens"] += prompt
        self._usage["completion_tokens"] += completion
        self._usage["total_tokens"] += prompt + completion

    def _redact(self, text: str) -> str:
        """Strip this client's API key from text destined for logs/errors."""

        if self.api_key and self.api_key in text:
            return text.replace(self.api_key, "***")
        return text

    def _raise_for_status(self, response: httpx.Response, provider: str) -> None:
        """Raise HTTPStatusError (agents retry 429/5xx) with a redacted body.

        The message deliberately excludes the request URL so providers that
        authenticate via query parameter (Gemini ``?key=``) can never leak a
        key into ``review.error_message`` or logs.
        """

        if response.status_code >= 400:
            detail = self._redact(response.text[:300])
            raise httpx.HTTPStatusError(
                f"{provider} API error {response.status_code}: {detail}",
                request=response.request,
                response=response,
            )


class GroqLLMClient(BaseLLMClient):
    """Adapter around the existing ``groq.GroqClient`` (which stays unchanged)."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        # GroqClient falls back to settings.GROQ_API_KEY/GROQ_MODEL on empty.
        self._client = GroqClient(api_key=api_key or None, model=model or None)
        super().__init__(api_key=self._client.api_key, model=self._client.model)

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        data = await self._client.generate_with_usage(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record_usage(data.get("prompt_tokens"), data.get("completion_tokens"))
        return data["text"]

    @property
    def model_name(self) -> str:
        return self._client.model


class OpenAILLMClient(BaseLLMClient):
    """OpenAI chat completions over plain REST (no SDK)."""

    BASE_URL = "https://api.openai.com/v1"

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as http:
            response = await http.post(
                f"{self.BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        self._raise_for_status(response, "OpenAI")

        data = response.json()
        usage = data.get("usage") or {}
        self._record_usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content")
        return content if isinstance(content, str) else ""

    @property
    def model_name(self) -> str:
        return self.model


class AnthropicLLMClient(BaseLLMClient):
    """Anthropic Messages API over plain REST (no SDK)."""

    BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as http:
            response = await http.post(
                f"{self.BASE_URL}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.API_VERSION,
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        self._raise_for_status(response, "Anthropic")

        data = response.json()
        usage = data.get("usage") or {}
        self._record_usage(usage.get("input_tokens"), usage.get("output_tokens"))
        blocks = data.get("content") or []
        return "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )

    @property
    def model_name(self) -> str:
        return self.model


class GeminiLLMClient(BaseLLMClient):
    """Google Gemini generateContent (REST pattern of the legacy gemini.py)."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as http:
            response = await http.post(
                f"{self.BASE_URL}/{self.model}:generateContent",
                params={"key": self.api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                    },
                },
            )
        self._raise_for_status(response, "Gemini")

        data = response.json()
        metadata = data.get("usageMetadata") or {}
        self._record_usage(
            metadata.get("promptTokenCount"),
            metadata.get("candidatesTokenCount"),
        )
        candidates = data.get("candidates") or []
        content = candidates[0].get("content") if candidates else None
        parts = content.get("parts") if isinstance(content, dict) else None
        return "".join(
            part.get("text", "") for part in parts or [] if isinstance(part, dict)
        )

    @property
    def model_name(self) -> str:
        return self.model


class OllamaLLMClient(BaseLLMClient):
    """Local Ollama chat endpoint (no API key required)."""

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, model: str, base_url: str | None = None) -> None:
        super().__init__(api_key="", model=model)
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT) as http:
            response = await http.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            )
        self._raise_for_status(response, "Ollama")

        data = response.json()
        self._record_usage(
            data.get("prompt_eval_count"),
            data.get("eval_count"),
        )
        message = data.get("message") or {}
        content = message.get("content")
        return content if isinstance(content, str) else ""

    @property
    def model_name(self) -> str:
        return self.model


def _default_client() -> GroqLLMClient:
    """System default Groq client (settings.GROQ_API_KEY / GROQ_MODEL)."""

    return GroqLLMClient(api_key=settings.GROQ_API_KEY, model=settings.GROQ_MODEL)


def resolve_llm_client(
    provider: str | None,
    model: str | None,
    api_key_encrypted: str | None,
    base_url: str | None = None,
) -> BaseLLMClient:
    """Resolve the user's LLM client — ALWAYS returns a working client.

    Falls back to the system Groq default when: no personal config is
    stored, the provider is unknown, or decryption fails (e.g. rotated
    ``LLM_ENCRYPTION_KEY``). Never raises (hard constraint).
    """

    try:
        # No personal key stored (Ollama needs none) -> system default.
        if not provider or (not api_key_encrypted and provider != "ollama"):
            if provider and provider != "ollama":
                logger.info(
                    "LLM settings for provider %r have no stored key; using system default",
                    provider,
                )
            return _default_client()

        # Ollama needs no key — no decryption involved.
        if provider == "ollama":
            return OllamaLLMClient(
                model=model or "llama3",
                base_url=base_url,
            )

        api_key = decrypt_api_key(api_key_encrypted or "")

        match provider:
            case "groq":
                return GroqLLMClient(
                    api_key=api_key, model=model or settings.GROQ_MODEL
                )
            case "openai":
                return OpenAILLMClient(api_key=api_key, model=model or "gpt-4o")
            case "anthropic":
                return AnthropicLLMClient(
                    api_key=api_key, model=model or "claude-sonnet-4-6"
                )
            case "gemini":
                return GeminiLLMClient(
                    api_key=api_key, model=model or "gemini-2.5-flash"
                )
            case _:
                logger.warning(
                    "Unknown LLM provider %r; falling back to system default",
                    provider,
                )
                return _default_client()
    except Exception as exc:  # noqa: BLE001 — constraint: resolve must never raise
        logger.warning(
            "resolve_llm_client failed (%s: %s); falling back to system default",
            type(exc).__name__,
            exc,
        )
        return _default_client()
