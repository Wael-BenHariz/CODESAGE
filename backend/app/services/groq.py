"""Groq API client (OpenAI-compatible chat completions endpoint).

Mirrors the method surface of the legacy GeminiClient so the review
orchestrator, specialist agents, and worker swap providers without any
changes to call sites' semantics:

- generate(prompt, temperature, max_tokens) -> str
- generate_with_usage(...) -> {"text", "prompt_tokens", "completion_tokens", "total_tokens"}
- total_usage() -> aggregate dict across this client instance

Errors are raised as httpx.HTTPStatusError with the response body attached
so the agents' transient-error backoff (429/5xx) and the worker's error
classifier keep working unchanged.

Note: Groq's Cloudflare layer blocks python-urllib's default User-Agent
(1010) but accepts python-httpx, which this client uses.
"""

from typing import Any, Optional

import httpx

from app.config import settings


class GroqClient:
    """Async Groq API client shared by review services and agents."""

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL
        self.usage_records: list[dict[str, int]] = []

    async def generate(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate Groq text for a prompt."""

        response = await self.generate_with_usage(prompt, temperature, max_tokens)
        return response["text"]

    async def generate_with_usage(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Generate Groq text and return token usage metadata."""

        url = f"{self.BASE_URL}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)

            # Raise HTTPStatusError (same type the agents retry on 429/5xx)
            # but attach the response body for diagnosis — Groq errors carry
            # actionable messages (rate limits, model deprecation).
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"Groq API error {response.status_code}: {response.text[:300]}",
                    request=response.request,
                    response=response,
                )

            data = response.json()
            usage = data.get("usage") or {}

            # Tolerant extraction: missing/empty content yields "" so callers
            # retry with a clear error instead of crashing on KeyError.
            choices = data.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            content = message.get("content")
            text = content if isinstance(content, str) else ""

            result = {
                "text": text,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
            self.usage_records.append(
                {
                    "prompt_tokens": result["prompt_tokens"],
                    "completion_tokens": result["completion_tokens"],
                    "total_tokens": result["total_tokens"],
                }
            )
            return result

    def total_usage(self) -> dict[str, int]:
        """Return aggregate usage for calls made through this client instance."""

        return {
            "prompt_tokens": sum(record.get("prompt_tokens", 0) for record in self.usage_records),
            "completion_tokens": sum(
                record.get("completion_tokens", 0) for record in self.usage_records
            ),
            "total_tokens": sum(record.get("total_tokens", 0) for record in self.usage_records),
        }
