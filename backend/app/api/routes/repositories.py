"""
Repository Routes
Repository management and configuration endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.db.models import User, Repository, GitHubInstallation
from app.schemas.repository import (
    RepositoryResponse,
    RepositoryUpdate,
    RepositoryListResponse,
    RepositoryDetail,
    RepositorySettings,
)
from app.security.dependencies import get_current_user

router = APIRouter()


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
    
    # Get review stats
    from app.db.models import Review
    reviews_count = await db.execute(
        select(func.count(Review.id))
        .join_from(Review, Repository)
        .where(Repository.id == repository_id)
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