"""
Pull Request Routes
Pull request management and review triggering endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.db.models import User, Repository, PullRequest, Review
from app.schemas.pull_request import (
    PullRequestResponse,
    PullRequestListResponse,
    PullRequestWithReviews,
)
from app.schemas.review import ReviewResponse
from app.security.dependencies import get_current_user

router = APIRouter()


@router.get("/repository/{repository_id}", response_model=PullRequestListResponse)
async def list_pull_requests(
    repository_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    state: Optional[str] = Query(None, description="Filter by state (open, closed, merged)"),
    author: Optional[str] = Query(None, description="Filter by author login"),
):
    """
    List pull requests for a repository.
    """
    # Verify repository exists
    repo_result = await db.execute(
        select(Repository).where(Repository.id == repository_id)
    )
    if not repo_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    
    # Build query
    query = select(PullRequest).where(PullRequest.repository_id == repository_id)
    count_query = select(func.count(PullRequest.id)).where(PullRequest.repository_id == repository_id)
    
    # Apply filters
    if state:
        query = query.where(PullRequest.state == state)
        count_query = count_query.where(PullRequest.state == state)
    
    if author:
        query = query.where(PullRequest.author_login == author)
        count_query = count_query.where(PullRequest.author_login == author)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Get paginated results
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page).order_by(PullRequest.created_at.desc())
    
    result = await db.execute(query)
    prs = result.scalars().all()
    
    return PullRequestListResponse(
        items=[PullRequestResponse.model_validate(pr) for pr in prs],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{pull_request_id}", response_model=PullRequestWithReviews)
async def get_pull_request(
    pull_request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get pull request by ID with reviews.
    """
    result = await db.execute(
        select(PullRequest)
        .options(selectinload(PullRequest.reviews))
        .where(PullRequest.id == pull_request_id)
    )
    pr = result.scalar_one_or_none()
    
    if not pr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found",
        )
    
    # Get latest review
    latest_review = None
    if pr.reviews:
        latest_review = max(pr.reviews, key=lambda r: r.created_at)
    
    response = PullRequestWithReviews(
        id=str(pr.id),
        repository_id=str(pr.repository_id),
        github_pr_id=pr.github_pr_id,
        number=pr.number,
        title=pr.title,
        body=pr.body,
        state=pr.state,
        author_login=pr.author_login,
        author_avatar_url=pr.author_avatar_url,
        base_branch=pr.base_branch,
        head_branch=pr.head_branch,
        base_sha=pr.base_sha,
        head_sha=pr.head_sha,
        additions=pr.additions,
        deletions=pr.deletions,
        changed_files=pr.changed_files,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        reviews_count=len(pr.reviews),
        latest_review_id=str(latest_review.id) if latest_review else None,
        latest_review_status=latest_review.status if latest_review else None,
    )
    
    return response


@router.post("/{pull_request_id}/review")
async def trigger_review(
    pull_request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Trigger a code review for a pull request.
    The review will be processed asynchronously.
    """
    result = await db.execute(
        select(PullRequest)
        .options(selectinload(PullRequest.repository))
        .where(PullRequest.id == pull_request_id)
    )
    pr = result.scalar_one_or_none()
    
    if not pr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found",
        )
    
    # Check if repository is enabled
    if not pr.repository.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CodeSage is disabled for this repository",
        )
    
    # Check for pending review
    pending_review = await db.execute(
        select(Review)
        .where(Review.pull_request_id == pull_request_id)
        .where(Review.status.in_(["pending", "processing"]))
    )
    if pending_review.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A review is already in progress",
        )
    
    # Create new review
    from datetime import datetime, timezone
    review = Review(
        pull_request_id=pr.id,
        user_id=current_user.id,
        status="pending",
        started_at=datetime.now(timezone.utc),
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    
    # Queue the review job (will be picked up by worker)
    try:
        from app.workers.review_queue import queue_review
        await queue_review(str(review.id))
    except Exception:
        # Update review status to failed if queue fails
        review.status = "failed"
        review.error_message = "Failed to queue review"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue review",
        )
    
    return {
        "review_id": str(review.id),
        "status": "pending",
        "message": "Review queued successfully",
    }


@router.get("/{pull_request_id}/reviews", response_model=list[ReviewResponse])
async def list_reviews(
    pull_request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all reviews for a pull request.
    """
    # Verify PR exists
    pr_result = await db.execute(
        select(PullRequest).where(PullRequest.id == pull_request_id)
    )
    if not pr_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found",
        )
    
    result = await db.execute(
        select(Review)
        .where(Review.pull_request_id == pull_request_id)
        .order_by(Review.created_at.desc())
    )
    reviews = result.scalars().all()
    
    return [ReviewResponse.model_validate(r) for r in reviews]