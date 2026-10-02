"""
Review Routes
Review status and comment management endpoints.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.db.models import Review, ReviewComment, ScanFindingRow, ScanReportRow, User
from app.schemas.review import (
    ReviewResponse,
    ReviewWithComments,
    ReviewStatus,
    ReviewListResponse,
    ReviewCommentResponse,
)
from app.schemas.scan_report import ScanReportResponse
from app.security.dependencies import get_current_user
from app.security.roles import require_developer
from app.services.scan_report_store import finding_from_row

router = APIRouter()

# Scan-report filter vocabularies (mirrors the schema's literals).
_SCAN_TOOLS = ("sonarqube", "semgrep")
_SCAN_SEVERITIES = ("info", "low", "medium", "high", "critical")
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# starlette >= 1.x renamed HTTP_422_UNPROCESSABLE_ENTITY (accessing the old
# name emits a deprecation warning on every call); 422 for older versions.
_UNPROCESSABLE_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


@router.get("", response_model=ReviewListResponse)
async def list_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    pull_request_id: Optional[str] = Query(None, description="Filter by pull request"),
):
    """
    List all reviews (admin only).
    """
    # Build query
    query = select(Review)
    count_query = select(func.count(Review.id))

    # Apply filters
    if status_filter:
        query = query.where(Review.status == status_filter)
        count_query = count_query.where(Review.status == status_filter)

    if pull_request_id:
        query = query.where(Review.pull_request_id == pull_request_id)
        count_query = count_query.where(Review.pull_request_id == pull_request_id)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Get paginated results
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page).order_by(Review.created_at.desc())

    result = await db.execute(query)
    reviews = result.scalars().all()

    return ReviewListResponse(
        items=[ReviewResponse.model_validate(r) for r in reviews],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{review_id}", response_model=ReviewWithComments)
async def get_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get review by ID with all comments.
    """
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.comments))
        .where(Review.id == review_id)
    )
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    return ReviewWithComments(
        id=str(review.id),
        pull_request_id=str(review.pull_request_id),
        user_id=str(review.user_id) if review.user_id else None,
        status=review.status,
        error_message=review.error_message,
        summary=review.summary,
        gemini_model=review.gemini_model,
        tokens_used=review.tokens_used,
        started_at=review.started_at,
        completed_at=review.completed_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
        comments_count=len(review.comments),
        comments=[
            ReviewCommentResponse(
                id=str(c.id),
                review_id=str(c.review_id),
                pull_request_id=str(c.pull_request_id),
                github_comment_id=c.github_comment_id,
                file_path=c.file_path,
                line_number=c.line_number,
                body=c.body,
                severity=c.severity,
                category=c.category,
                resolved=c.resolved,
                resolved_at=c.resolved_at,
                created_at=c.created_at,
            )
            for c in review.comments
        ],
    )


@router.get("/{review_id}/scan-report", response_model=ScanReportResponse)
async def get_scan_report(
    review_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    tool: Annotated[
        str | None,
        Query(description="Only findings from this tool (sonarqube|semgrep)"),
    ] = None,
    severity: Annotated[
        str | None,
        Query(description="Only findings at this unified severity (info..critical)"),
    ] = None,
):
    """
    Latest unified static-analysis scan for a review (SonarQube + Semgrep).

    404 for an unknown review or a review that has no scan report yet;
    422 for filter values outside the vocabulary. ``summary`` always
    describes the FULL scan — filters only narrow ``findings``.
    """
    if tool is not None and tool not in _SCAN_TOOLS:
        raise HTTPException(
            status_code=_UNPROCESSABLE_422,
            detail=f"Unknown tool {tool!r}; expected one of {_SCAN_TOOLS}",
        )
    if severity is not None and severity not in _SCAN_SEVERITIES:
        raise HTTPException(
            status_code=_UNPROCESSABLE_422,
            detail=(
                f"Unknown severity {severity!r}; " f"expected one of {_SCAN_SEVERITIES}"
            ),
        )

    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    report_result = await db.execute(
        select(ScanReportRow)
        .where(ScanReportRow.review_id == review.id)
        .order_by(ScanReportRow.created_at.desc())
        .limit(1)
    )
    report = report_result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No scan report for this review",
        )

    stmt = select(ScanFindingRow).where(ScanFindingRow.report_id == report.id)
    if tool is not None:
        stmt = stmt.where(ScanFindingRow.tool == tool)
    if severity is not None:
        stmt = stmt.where(ScanFindingRow.severity == severity)
    findings = [finding_from_row(row) for row in (await db.execute(stmt)).scalars()]

    # Strongest first, then by file/line — deterministic across reads.
    findings.sort(
        key=lambda f: (
            -_SEVERITY_RANK.get(f.severity, 0),
            f.file_path,
            f.line_start if f.line_start is not None else 10**9,
        )
    )

    return ScanReportResponse(
        scan_id=report.scan_id,
        review_id=str(review.id),
        tools_run=list(report.tools_run or []),
        tools_failed=list(report.tools_failed or []),
        summary=dict(report.summary or {}),
        findings=findings,
        created_at=report.created_at,
    )


@router.get("/{review_id}/status", response_model=ReviewStatus)
async def get_review_status(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # noqa: B008
):
    """
    Get review processing status.
    Useful for polling review progress.

    Authenticated like ``GET /reviews/{review_id}``: any logged-in user may
    read a review (reviews are shared across users — no ownership filter).
    """
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    # Calculate progress
    progress = None
    if review.status == "processing" and review.started_at:
        # Estimate progress based on time (placeholder)
        from datetime import datetime, timezone, timedelta

        elapsed = (datetime.now(timezone.utc) - review.started_at).total_seconds()
        progress = min(95.0, elapsed / 30 * 100)  # Assume 30 seconds for 100%

    return ReviewStatus(
        review_id=str(review.id),
        status=review.status,
        progress=progress,
        started_at=review.started_at,
        completed_at=review.completed_at,
        error_message=review.error_message,
    )


@router.post("/{review_id}/retry")
async def retry_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_developer),
):
    """
    Retry a failed review.
    """
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    if review.status not in ["failed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only retry failed reviews",
        )

    # Reset review status
    from datetime import datetime, timezone

    review.status = "pending"
    review.error_message = None
    review.started_at = datetime.now(timezone.utc)
    await db.commit()

    # Queue the review job
    try:
        from app.workers.review_queue import queue_review

        await queue_review(review_id)
    except Exception:
        review.status = "failed"
        review.error_message = "Failed to queue review"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue review",
        )

    return {
        "review_id": review_id,
        "status": "pending",
        "message": "Review retry queued successfully",
    }


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_developer),
):
    """
    Delete a review and its comments.
    """
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    await db.delete(review)
    await db.commit()


@router.patch("/{review_id}/comments/{comment_id}/resolve")
async def resolve_comment(
    review_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_developer),
):
    """
    Mark a review comment as resolved.
    """
    result = await db.execute(
        select(ReviewComment)
        .where(ReviewComment.id == comment_id)
        .where(ReviewComment.review_id == review_id)
    )
    comment = result.scalar_one_or_none()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )

    from datetime import datetime, timezone

    comment.resolved = True
    comment.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    return ReviewCommentResponse.model_validate(comment)
