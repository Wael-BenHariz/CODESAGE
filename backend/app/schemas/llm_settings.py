"""LLM Settings Schemas

Request/response models for the per-user LLM provider configuration
endpoints. The API key is write-only: it is accepted in plaintext on PUT
and never serialized back out — responses only expose ``has_api_key``.

Validation split (hard constraint: blank/absent api_key must PRESERVE the
stored key, never clear it, and only be rejected when the user has no key
stored at all) — so api_key presence is checked in the route (DB-aware),
not here.
"""

from typing import Literal

from pydantic import BaseModel, field_validator


class LLMSettingsResponse(BaseModel):
    """Current LLM settings — never includes the key or its encrypted blob."""

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    has_api_key: bool = False
    is_using_default: bool = True


class LLMSettingsUpdate(BaseModel):
    """PUT payload.

    ``api_key`` absent or empty = keep the stored encrypted key (also the
    path for "blank password field while a key is already saved").
    ``base_url`` defaults to the local Ollama daemon when provider=ollama
    and no URL is supplied.
    """

    provider: Literal["groq", "openai", "anthropic", "gemini", "ollama"]
    model: str
    api_key: str | None = None
    base_url: str | None = None

    @field_validator("model", mode="after")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model must not be empty")
        return stripped


class LLMTestResponse(BaseModel):
    """Result of POST /settings/llm/test (server-side key, never re-sent)."""

    success: bool
    response: str | None = None
    error: str | None = None
    model: str
    latency_ms: int
