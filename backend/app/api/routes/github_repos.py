"""GitHub App repository selection routes."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import User, WatchedRepo
from app.security.dependencies import get_current_user
from app.security.roles import require_developer
from app.services import repo_tenant
from app.services.github_app import get_installation_repos

logger = logging.getLogger(__name__)

router = APIRouter()


class RepoSelectionItem(BaseModel):
    id: int = Field(..., description="GitHub repository ID")
    name: str = Field(..., description="GitHub repository full name")
    private: bool = Field(..., description="Whether the repository is private")
    enabled: bool = Field(..., description="Whether reviews are enabled")


class RepoSelectionPayload(BaseModel):
    repos: list[RepoSelectionItem]
    sync: bool = Field(
        default=False,
        description=(
            "Treat the payload as the complete desired state: watched repos "
            "missing from it are disabled (deselect)."
        ),
    )


class RepoStatusResponse(BaseModel):
    installed: bool
    installation_id: Optional[int]


class RepoResponse(BaseModel):
    id: int
    name: str
    private: bool
    enabled: bool


@router.get("/status", response_model=RepoStatusResponse)
async def get_github_app_status(
    current_user: User = Depends(get_current_user),
):
    return RepoStatusResponse(
        installed=current_user.github_installation_id is not None,
        installation_id=current_user.github_installation_id,
    )


@router.get("/repos", response_model=list[RepoResponse])
async def get_github_app_repos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    installation_id = current_user.github_installation_id
    if installation_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub App not installed",
        )

    watched_result = await db.execute(
        select(WatchedRepo).where(WatchedRepo.user_id == current_user.id)
    )
    watched_repos = {item.repo_id: item for item in watched_result.scalars().all()}

    try:
        repos = await get_installation_repos(installation_id)
    except httpx.HTTPStatusError as exc:
        # Stale/removed installation: surface a fixable 409, not an opaque 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GitHub installation is invalid or removed. Reinstall the GitHub App.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach GitHub to list repositories.",
        ) from exc
    return [
        RepoResponse(
            id=repo["id"],
            name=repo["name"],
            private=repo.get("private", False),
            enabled=watched_repos.get(repo["id"]).enabled if repo["id"] in watched_repos else False,
        )
        for repo in repos
    ]


@router.post("/repos/selection")
async def save_github_app_repo_selection(
    payload: RepoSelectionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_developer),
):
    existing_result = await db.execute(
        select(WatchedRepo).where(WatchedRepo.user_id == current_user.id)
    )
    existing = {item.repo_id: item for item in existing_result.scalars().all()}
    # Snapshot BEFORE mutating the rows — drives the repo-tenant
    # enable/disable transition diff below (one repo = one namespace).
    previously_enabled = {
        repo_id: bool(record.enabled) for repo_id, record in existing.items()
    }

    payload_ids: set[int] = set()
    for repo in payload.repos:
        payload_ids.add(repo.id)
        record = existing.get(repo.id)
        if record:
            record.repo_name = repo.name
            record.enabled = repo.enabled
        else:
            db.add(
                WatchedRepo(
                    user_id=current_user.id,
                    repo_id=repo.id,
                    repo_name=repo.name,
                    enabled=repo.enabled,
                )
            )

    sync_disabled: list[int] = []
    if payload.sync:
        # Full-state payload: watched repos absent from it are no longer
        # selected (e.g. deselected or removed from the installation).
        for record in existing.values():
            if record.repo_id not in payload_ids:
                if previously_enabled.get(record.repo_id):
                    sync_disabled.append(record.repo_id)
                record.enabled = False

    await db.commit()

    # ── Best-effort mirror into repo-tenant-service ────────────────────────
    # Transitions only: newly-enabled -> enable (creates the namespace),
    # newly-disabled -> disable (teardown). Both are idempotent server-side,
    # and failures are swallowed inside the client — the selection above is
    # already committed and must never surface a 5xx because the
    # microservice is down.
    enable_calls = [
        repo_tenant.enable_repo(
            repo_id=repo.id, full_name=repo.name, owner_user_id=current_user.id
        )
        for repo in payload.repos
        if repo.enabled and not previously_enabled.get(repo.id, False)
    ]
    disable_ids = [
        repo.id
        for repo in payload.repos
        if not repo.enabled and previously_enabled.get(repo.id, False)
    ]
    disable_calls = [
        repo_tenant.disable_repo(repo_id) for repo_id in (*disable_ids, *sync_disabled)
    ]

    if enable_calls or disable_calls:
        results = await asyncio.gather(
            *enable_calls, *disable_calls, return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("repo-tenant hook failed unexpectedly: %s", result)

    return {"saved": True}
