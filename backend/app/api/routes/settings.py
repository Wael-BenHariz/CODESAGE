"""LLM Settings Routes

Per-user LLM provider/model/key configuration. API keys are Fernet-
encrypted before storage; no endpoint ever returns the plaintext key or
its encrypted blob — only ``has_api_key`` / ``is_using_default`` flags.

- GET    /settings/llm        current flags (never the key)
- PUT    /settings/llm        save provider/model/key (blank key = keep)
- DELETE /settings/llm        clear all four columns -> system default
- POST   /settings/llm/test   ping the SAVED config (key decrypted
                              server-side, never re-sent by the client)
"""

import logging
import time
from typing import Annotated

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import User
from app.schemas.llm_settings import (
    LLMSettingsResponse,
    LLMSettingsUpdate,
    LLMTestResponse,
)
from app.security.dependencies import get_current_user
from app.security.encryption import decrypt_api_key, encrypt_api_key
from app.security.roles import require_developer
from app.services.llm_client import resolve_llm_client

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


def _to_response(user: User) -> LLMSettingsResponse:
    """Project the user's LLM columns — never the key or its blob."""

    return LLMSettingsResponse(
        provider=user.llm_provider,
        model=user.llm_model,
        base_url=user.llm_base_url,
        has_api_key=bool(user.llm_api_key),
        is_using_default=user.llm_provider is None,
    )


@router.get("/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Return the current user's LLM settings (flags only, never the key)."""

    return _to_response(current_user)


@router.put("/llm")
async def update_llm_settings(
    body: LLMSettingsUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_developer)],  # noqa: B008
):
    """Persist provider/model/key.

    ``api_key`` semantics (hard constraint): present + non-empty -> encrypt
    and overwrite; absent or empty -> keep the stored encrypted value.
    Requiring a key is DB-aware: rejected only for keyed providers when
    nothing is stored yet (ollama never needs one).
    """

    if body.provider != "ollama" and not body.api_key and not current_user.llm_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_key is required for this provider (or keep your existing key)",
        )

    base_url = body.base_url
    if body.provider == "ollama":
        base_url = base_url or DEFAULT_OLLAMA_BASE_URL
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="base_url must be a valid http(s) URL for ollama",
            )

    current_user.llm_provider = body.provider
    current_user.llm_model = body.model
    if body.api_key:
        current_user.llm_api_key = encrypt_api_key(body.api_key)
    # Non-ollama providers usually send null -> clears a stale Ollama URL.
    current_user.llm_base_url = base_url
    await db.commit()

    logger.info(
        "LLM settings updated for user %s: provider=%s model=%s key_rotated=%s",
        current_user.login,
        body.provider,
        body.model,
        bool(body.api_key),
    )
    return {"saved": True}


@router.delete("/llm")
async def clear_llm_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_developer)],  # noqa: B008
):
    """Clear all LLM settings — revert to the system default Groq client."""

    current_user.llm_provider = None
    current_user.llm_model = None
    current_user.llm_api_key = None
    current_user.llm_base_url = None
    await db.commit()

    logger.info("LLM settings cleared for user %s (system default)", current_user.login)
    return {"cleared": True}


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_developer)],  # noqa: B008
):
    """Send a minimal prompt through the SAVED configuration.

    The key is decrypted server-side (never accepted from the client) and
    redacted from any error text returned or logged.
    """

    llm_client = resolve_llm_client(
        provider=current_user.llm_provider,
        model=current_user.llm_model,
        api_key_encrypted=current_user.llm_api_key,
        base_url=current_user.llm_base_url,
    )
    model = llm_client.model_name

    # Redaction material: the stored key when it still decrypts. A rotated
    # LLM_ENCRYPTION_KEY already made resolve fall back (nothing to hide).
    stored_plain = ""
    if current_user.llm_api_key:
        try:
            stored_plain = decrypt_api_key(current_user.llm_api_key)
        except InvalidToken:
            stored_plain = ""

    started = time.perf_counter()
    try:
        text = await llm_client.complete(
            prompt="Reply with exactly: OK",
            temperature=0.0,
            max_tokens=20,
        )
    except Exception as exc:  # noqa: BLE001 — any failure = success:false
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = str(exc)[:300]
        if stored_plain and stored_plain in error:
            error = error.replace(stored_plain, "***")
        logger.warning(
            "LLM connection test failed for user %s (model=%s): %s",
            current_user.login,
            model,
            error,
        )
        return LLMTestResponse(
            success=False,
            error=error or type(exc).__name__,
            model=model,
            latency_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    return LLMTestResponse(
        success=True,
        response=text.strip()[:200] or "(empty response)",
        model=model,
        latency_ms=latency_ms,
    )
