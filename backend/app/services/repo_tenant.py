"""Best-effort client for the repo-tenant-service microservice.

repo-tenant-service owns the "one enabled repo = one Kubernetes namespace"
mapping. The CodeSage backend calls it whenever a watched repo flips:

- enable  -> POST /api/v1/repos/internal/enable
- disable -> POST /api/v1/repos/internal/disable

Every function here NEVER raises: saving watched_repos (and webhook
processing) must succeed even when repo-tenant-service is down. Failures
are logged as warnings so a missed teardown can be replayed manually.

Payload keys are camelCase — that is repo-tenant-service's default JSON
naming strategy (Spring), unlike this backend's snake_case API.
"""

import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "X-Service-Token": settings.REPO_TENANT_INTERNAL_TOKEN,
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return settings.REPO_TENANT_SERVICE_URL.rstrip("/")


async def enable_repo(
    *, repo_id: int, full_name: str, owner_user_id: UUID | None = None
) -> bool:
    """Tell repo-tenant-service a repo was enabled (idempotent server-side)."""
    payload: dict[str, Any] = {
        "repoId": repo_id,
        "fullName": full_name,
        "ownerUserId": str(owner_user_id) if owner_user_id else None,
    }
    url = f"{_base_url()}/api/v1/repos/internal/enable"

    try:
        async with httpx.AsyncClient(
            timeout=settings.REPO_TENANT_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(url, json=payload, headers=_headers())
            response.raise_for_status()
        logger.info(
            "repo-tenant enable accepted: repo_id=%s full_name=%s status=%s",
            repo_id,
            full_name,
            response.status_code,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort by design
        logger.warning(
            "repo-tenant enable failed (best-effort) repo_id=%s: %s", repo_id, exc
        )
        return False


async def disable_repo(repo_id: int) -> bool:
    """Tell repo-tenant-service a repo was disabled (teardown; idempotent)."""
    payload = {"repoId": repo_id}
    url = f"{_base_url()}/api/v1/repos/internal/disable"

    try:
        async with httpx.AsyncClient(
            timeout=settings.REPO_TENANT_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(url, json=payload, headers=_headers())
            response.raise_for_status()
        logger.info(
            "repo-tenant disable accepted: repo_id=%s status=%s",
            repo_id,
            response.status_code,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort by design
        logger.warning(
            "repo-tenant disable failed (best-effort) repo_id=%s: %s", repo_id, exc
        )
        return False
