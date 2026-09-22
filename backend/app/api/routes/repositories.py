"""
Repository Routes
Repository management and configuration endpoints.
"""

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.db.models import GitHubInstallation, OAuthToken, Repository, User
from app.schemas.repository import (
    RepositoryResponse,
    RepositoryUpdate,
    RepositoryListResponse,
    RepositoryDetail,
    RepositorySettings,
)
from app.security.dependencies import get_current_user
from app.services.github import github_service

router = APIRouter()

installation_states: dict[str, int] = {}


class GitHubRepoInfo(BaseModel):
    """GitHub repository info from the GitHub API."""
    id: int
    name: str
    full_name: str
    private: bool
    default_branch: str
    description: Optional[str] = None
    language: Optional[str] = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0


class GitHubAppInstallUrl(BaseModel):
    """GitHub App installation URL response."""

    installation_url: str
    state: str


class GitHubInstallationSyncResponse(BaseModel):
    """Result of syncing one GitHub App installation."""

    installation_id: int
    repositories_synced: int


@router.get("/install-url", response_model=GitHubAppInstallUrl)
async def get_github_app_install_url(
    current_user: User = Depends(get_current_user),
):
    """Return the GitHub App installation URL for repository access."""

    state = secrets.token_urlsafe(32)
    installation_states[state] = current_user.github_id
    return GitHubAppInstallUrl(
        installation_url=github_service.get_app_installation_url(state),
        state=state,
    )


@router.post("/installations/sync", response_model=GitHubInstallationSyncResponse)
async def sync_github_app_installation(
    installation_id: int = Query(..., description="GitHub App installation ID"),
    state: Optional[str] = Query(None, description="Optional installation state returned by GitHub"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync a real GitHub App installation and its accessible repositories."""

    if state is not None:
        expected_github_id = installation_states.pop(state, None)
        if expected_github_id != current_user.github_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid installation state",
            )

    installation_data = await github_service.get_app_installation(installation_id)
    installation = await _upsert_installation(db, installation_data)
    await _ensure_installation_accessible_to_user(db, installation, current_user)
    repos = await _sync_installation_repositories(db, installation, installation_id)
    await db.commit()

    return GitHubInstallationSyncResponse(
        installation_id=installation_id,
        repositories_synced=len(repos),
    )


@router.get("/github", response_model=list[GitHubRepoInfo])
async def list_github_repos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List repositories accessible through the user's GitHub App installation.
    """
    installations = await _get_user_installations(db, current_user)
    if not installations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Install the GitHub App before connecting repositories.",
        )

    connected_result = await db.execute(select(Repository.full_name))
    connected_names = {r[0] for r in connected_result.all()}

    response: list[GitHubRepoInfo] = []
    seen_repo_ids: set[int] = set()
    for installation in installations:
        repos = await github_service.get_installed_repos(installation.installation_id)
        for repo in repos:
            repo_id = repo["id"]
            if repo_id in seen_repo_ids or repo["full_name"] in connected_names:
                continue
            seen_repo_ids.add(repo_id)
            response.append(
                GitHubRepoInfo(
                    id=repo_id,
                    name=repo["name"],
                    full_name=repo["full_name"],
                    private=repo.get("private", False),
                    default_branch=repo.get("default_branch", "main"),
                    description=repo.get("description"),
                    language=repo.get("language"),
                    stargazers_count=repo.get("stargazers_count", 0),
                    forks_count=repo.get("forks_count", 0),
                    open_issues_count=repo.get("open_issues_count", 0),
                )
            )
    return response


async def _get_user_installations(
    db: AsyncSession,
    current_user: User,
) -> list[GitHubInstallation]:
    token_record = await _get_current_oauth_token(db, current_user)
    if token_record:
        github_installations = await github_service.get_user_app_installations(token_record.access_token)
        github_installation_ids = [item["id"] for item in github_installations]
        if github_installation_ids:
            result = await db.execute(
                select(GitHubInstallation).where(
                    GitHubInstallation.installation_id.in_(github_installation_ids)
                )
            )
            return list(result.scalars().all())

    result = await db.execute(
        select(GitHubInstallation).where(GitHubInstallation.account_id == current_user.github_id)
    )
    return list(result.scalars().all())


async def _ensure_installation_accessible_to_user(
    db: AsyncSession,
    installation: GitHubInstallation,
    current_user: User,
) -> None:
    if installation.account_id != current_user.github_id:
        token_record = await _get_current_oauth_token(db, current_user)
        if token_record:
            github_installations = await github_service.get_user_app_installations(token_record.access_token)
            accessible_ids = {item["id"] for item in github_installations}
            if installation.installation_id in accessible_ids:
                return

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Installation is not accessible to the authenticated GitHub user.",
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub token expired. Please log in again before syncing installations.",
        )


async def _get_current_oauth_token(
    db: AsyncSession,
    current_user: User,
) -> OAuthToken | None:
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == current_user.id)
    )
    token_record = result.scalar_one_or_none()
    if not token_record or token_record.is_expired:
        return None
    return token_record


async def _upsert_installation(
    db: AsyncSession,
    installation_data: dict,
) -> GitHubInstallation:
    installation_id = installation_data.get("id")
    account = installation_data.get("account", {})
    result = await db.execute(
        select(GitHubInstallation).where(GitHubInstallation.installation_id == installation_id)
    )
    record = result.scalar_one_or_none()

    if record:
        record.app_id = installation_data.get("app_id", record.app_id)
        record.account_id = account.get("id", record.account_id)
        record.account_login = account.get("login", record.account_login)
        record.account_type = account.get("type", record.account_type)
        record.permissions = installation_data.get("permissions", record.permissions)
        return record

    record = GitHubInstallation(
        app_id=installation_data.get("app_id", 0),
        installation_id=installation_id,
        account_id=account.get("id", 0),
        account_login=account.get("login", ""),
        account_type=account.get("type", "User"),
        permissions=installation_data.get("permissions", {}),
    )
    db.add(record)
    await db.flush()
    return record


async def _sync_installation_repositories(
    db: AsyncSession,
    installation: GitHubInstallation,
    github_installation_id: int,
) -> list[Repository]:
    repos_data = await github_service.get_installed_repos(github_installation_id)
    synced: list[Repository] = []
    for repo_data in repos_data:
        repo = await _upsert_repository(db, installation, repo_data)
        synced.append(repo)
    return synced


async def _upsert_repository(
    db: AsyncSession,
    installation: GitHubInstallation,
    repo_data: dict,
) -> Repository:
    result = await db.execute(
        select(Repository).where(Repository.github_repo_id == repo_data.get("id"))
    )
    repo = result.scalar_one_or_none()
    if repo:
        repo.installation_id = installation.id
        repo.name = repo_data.get("name", repo.name)
        repo.full_name = repo_data.get("full_name", repo.full_name)
        repo.private = repo_data.get("private", repo.private)
        repo.default_branch = repo_data.get("default_branch", repo.default_branch)
        return repo

    repo = Repository(
        installation_id=installation.id,
        github_repo_id=repo_data.get("id"),
        name=repo_data.get("name", ""),
        full_name=repo_data.get("full_name", ""),
        private=repo_data.get("private", False),
        default_branch=repo_data.get("default_branch", "main"),
        enabled=True,
    )
    db.add(repo)
    await db.flush()
    return repo


@router.post("/connect", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def connect_repository(
    github_repo_id: int = Query(..., description="GitHub repository ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Connect a GitHub repository to CodeSage.
    Requires repository access from a real GitHub App installation.
    """
    installations = await _get_user_installations(db, current_user)
    if not installations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Install the GitHub App before connecting repositories.",
        )

    existing = await db.execute(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository already connected",
        )

    selected_installation: GitHubInstallation | None = None
    selected_repo: dict | None = None
    for installation in installations:
        repos = await github_service.get_installed_repos(installation.installation_id)
        selected_repo = next((repo for repo in repos if repo.get("id") == github_repo_id), None)
        if selected_repo:
            selected_installation = installation
            break

    if not selected_installation or not selected_repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository is not available through the installed GitHub App.",
        )

    repo = await _upsert_repository(db, selected_installation, selected_repo)
    await db.commit()
    await db.refresh(repo)
    
    return RepositoryResponse.model_validate(repo)


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    search: Optional[str] = Query(None, description="Search by name"),
):
    """
    List all repositories accessible by the current user.
    """
    # Build base query for user's installations
    query = (
        select(Repository)
        .join(GitHubInstallation)
        .where(GitHubInstallation.account_id == current_user.github_id)
    )
    count_query = (
        select(func.count(Repository.id))
        .join(GitHubInstallation)
        .where(GitHubInstallation.account_id == current_user.github_id)
    )
    
    # Apply filters
    if enabled is not None:
        query = query.where(Repository.enabled == enabled)
        count_query = count_query.where(Repository.enabled == enabled)
    
    if search:
        search_filter = Repository.name.ilike(f"%{search}%") | Repository.full_name.ilike(f"%{search}%")
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Get paginated results
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page).order_by(Repository.created_at.desc())
    
    result = await db.execute(query)
    repos = result.scalars().all()
    
    return RepositoryListResponse(
        items=[RepositoryResponse.model_validate(r) for r in repos],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{repository_id}", response_model=RepositoryResponse)
async def get_repository(
    repository_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get repository by ID.
    """
    result = await db.execute(
        select(Repository)
        .options(selectinload(Repository.installation))
        .where(Repository.id == repository_id)
    )
    repo = result.scalar_one_or_none()
    
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    
    return RepositoryResponse.model_validate(repo)


@router.get("/{repository_id}/detail", response_model=RepositoryDetail)
async def get_repository_detail(
    repository_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed repository information with stats.
    """
    result = await db.execute(
        select(Repository)
        .options(
            selectinload(Repository.pull_requests),
            selectinload(Repository.installation),
        )
        .where(Repository.id == repository_id)
    )
    repo = result.scalar_one_or_none()
    
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    
    # Get review stats - join through PullRequest since Review has pull_request_id FK
    from app.db.models import Review, PullRequest
    reviews_count = await db.execute(
        select(func.count(Review.id))
        .join(PullRequest, Review.pull_request_id == PullRequest.id)
        .where(PullRequest.repository_id == repository_id)
        .where(Review.status == "completed")
    )
    
    return RepositoryDetail(
        id=str(repo.id),
        installation_id=str(repo.installation_id),
        github_repo_id=repo.github_repo_id,
        name=repo.name,
        full_name=repo.full_name,
        private=repo.private,
        default_branch=repo.default_branch,
        webhook_id=repo.webhook_id,
        enabled=repo.enabled,
        created_at=repo.created_at,
        updated_at=repo.updated_at,
        settings=RepositorySettings(),
        total_prs=len(repo.pull_requests),
        total_reviews=reviews_count.scalar_one() if reviews_count else 0,
    )


@router.patch("/{repository_id}", response_model=RepositoryResponse)
async def update_repository(
    repository_id: str,
    update_data: RepositoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update repository configuration.
    """
    result = await db.execute(
        select(Repository).where(Repository.id == repository_id)
    )
    repo = result.scalar_one_or_none()
    
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    
    # Update fields
    if update_data.enabled is not None:
        repo.enabled = update_data.enabled
    if update_data.default_branch is not None:
        repo.default_branch = update_data.default_branch
    
    await db.commit()
    await db.refresh(repo)
    
    return RepositoryResponse.model_validate(repo)


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repository_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a repository from CodeSage.
    This removes the webhook and stops tracking.
    """
    result = await db.execute(
        select(Repository).where(Repository.id == repository_id)
    )
    repo = result.scalar_one_or_none()
    
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    
    # Delete repository (cascades to PRs and reviews)
    await db.delete(repo)
    await db.commit()
