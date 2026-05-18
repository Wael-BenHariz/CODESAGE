"""
Repository Routes
Repository management and configuration endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.db.models import User, Repository, GitHubInstallation, OAuthToken
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


@router.get("/github", response_model=list[GitHubRepoInfo])
async def list_github_repos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List user's GitHub repositories (not yet connected to CodeSage).
    Uses the user's OAuth token to fetch repos from GitHub.
    """
    # Get user's OAuth token
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == current_user.id)
    )
    token_record = result.scalar_one_or_none()
    
    if not token_record or token_record.is_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub token expired. Please log in again.",
        )
    
    # Fetch repos from GitHub
    repos = await github_service.get_user_repos(token_record.access_token)
    
    # Filter out already connected repos
    connected_result = await db.execute(select(Repository.full_name))
    connected_names = {r[0] for r in connected_result.all()}
    
    return [
        GitHubRepoInfo(
            id=r["id"],
            name=r["name"],
            full_name=r["full_name"],
            private=r.get("private", False),
            default_branch=r.get("default_branch", "main"),
            description=r.get("description"),
            language=r.get("language"),
            stargazers_count=r.get("stargazers_count", 0),
            forks_count=r.get("forks_count", 0),
            open_issues_count=r.get("open_issues_count", 0),
        )
        for r in repos
        if r["full_name"] not in connected_names
    ]


@router.post("/connect", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def connect_repository(
    github_repo_id: int = Query(..., description="GitHub repository ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Connect a GitHub repository to CodeSage.
    Creates installation and repository records.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get user's OAuth token
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == current_user.id)
    )
    token_record = result.scalar_one_or_none()
    
    if not token_record or token_record.is_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub token expired. Please log in again.",
        )
    
    # Fetch repo details from GitHub
    repos = await github_service.get_user_repos(token_record.access_token)
    repo_data = next((r for r in repos if r["id"] == github_repo_id), None)
    
    if not repo_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found on GitHub",
        )
    
    # Check if already connected
    existing = await db.execute(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository already connected",
        )
    
    # Find or create installation for this user
    inst_result = await db.execute(
        select(GitHubInstallation).where(
            GitHubInstallation.account_id == current_user.github_id
        )
    )
    installation = inst_result.scalar_one_or_none()
    
    if not installation:
        installation = GitHubInstallation(
            app_id=0,
            installation_id=current_user.github_id,
            account_id=current_user.github_id,
            account_login=current_user.login,
            account_type="User",
            permissions={"pull_requests": "read", "contents": "read"},
        )
        db.add(installation)
        try:
            await db.flush()
        except Exception:
            await db.rollback()
            # Another request created it — fetch it
            inst_result = await db.execute(
                select(GitHubInstallation).where(
                    GitHubInstallation.account_id == current_user.github_id
                )
            )
            installation = inst_result.scalar_one_or_none()
            if not installation:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create repository installation",
                )
    
    # Create repository record
    repo = Repository(
        installation_id=installation.id,
        github_repo_id=github_repo_id,
        name=repo_data["name"],
        full_name=repo_data["full_name"],
        private=repo_data.get("private", False),
        default_branch=repo_data.get("default_branch", "main"),
        enabled=True,
    )
    db.add(repo)
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