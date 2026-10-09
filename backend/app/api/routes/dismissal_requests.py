"""Dismissal request endpoints for RBAC."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import (
    DismissalRequest,
    PullRequest,
    Review,
    ReviewComment,
    User,
)
from app.security.dependencies import get_current_user
from app.security.workspace_access import (
    check_permission_in_workspace,
    list_user_workspaces,
    self_review_blocked,
)

router = APIRouter(prefix="/dismissal-requests", tags=["dismissal-requests"])


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_dismissal_request(
    review_comment_id: UUID = Query(  # noqa: B008
        ..., description="ID of the review comment to request dismissal for"
    ),
    reason: str = Query(..., description="Reason for the dismissal request"),
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Create a dismissal request for a review comment.

    Only users in the TRIGGER_ROLES (DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN) can create dismissal requests.
    """
    # Check if the review comment exists
    comment_result = await db.execute(
        select(ReviewComment).where(ReviewComment.id == review_comment_id)
    )
    comment = comment_result.scalar_one_or_none()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review comment not found"
        )

    # Get the review to determine the workspace
    review_result = await db.execute(
        select(Review).where(Review.id == comment.review_id)
    )
    review = review_result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Associated review not found"
        )

    # Get the workspace from the review (we added workspace_id to reviews in the migration)
    workspace_id = review.workspace_id

    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    # Requesting a dismissal is a DEVELOPER+ action (REQUEST_ROLES, §2.3).
    await check_permission_in_workspace(db, current_user, workspace_id, "request")

    # Check if there's already a pending dismissal request for this comment by this user
    existing_result = await db.execute(
        select(DismissalRequest).where(
            DismissalRequest.review_comment_id == review_comment_id,
            DismissalRequest.requested_by == current_user.id,
            DismissalRequest.status == "PENDING",
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending dismissal request for this comment",
        )

    # Create the dismissal request
    dismissal_request = DismissalRequest(
        workspace_id=workspace_id,
        review_comment_id=review_comment_id,
        requested_by=current_user.id,
        reason=reason,
        status="PENDING",
    )
    db.add(dismissal_request)
    await db.commit()
    await db.refresh(dismissal_request)

    return {
        "id": str(dismissal_request.id),
        "workspace_id": str(dismissal_request.workspace_id),
        "review_comment_id": str(dismissal_request.review_comment_id),
        "requested_by": str(dismissal_request.requested_by),
        "reason": dismissal_request.reason,
        "status": dismissal_request.status,
        "created_at": dismissal_request.created_at,
        "updated_at": dismissal_request.updated_at,
    }


@router.get("", response_model=list[dict])
async def list_dismissal_requests(
    workspace_id: UUID | None = Query(  # noqa: B008
        None, description="Filter by workspace ID"
    ),
    status_filter: str | None = Query(
        None, description="Filter by status (PENDING, APPROVED, REJECTED)"
    ),
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """List dismissal requests.

    Users can see dismissal requests for workspaces they are members of.
    """
    # Accessible workspaces = personal workspace + every membership, merged
    # from both membership tables (see workspace_access.list_user_workspaces).
    accessible_workspace_ids = [
        workspace.id
        for workspace, _role in await list_user_workspaces(db, current_user)
    ]

    if not accessible_workspace_ids:
        return []  # User is not a member of any workspace

    # Build query for dismissal requests
    query = select(DismissalRequest).where(
        DismissalRequest.workspace_id.in_(accessible_workspace_ids)
    )

    # Apply workspace filter if specified
    if workspace_id:
        if workspace_id not in accessible_workspace_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to specified workspace",
            )
        query = query.where(DismissalRequest.workspace_id == workspace_id)

    # Apply status filter if specified
    if status_filter:
        if status_filter not in ["PENDING", "APPROVED", "REJECTED"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid status filter. Must be PENDING, APPROVED, or REJECTED",
            )
        query = query.where(DismissalRequest.status == status_filter)

    # Order by creation date (newest first)
    query = query.order_by(DismissalRequest.created_at.desc())

    # Execute query
    result = await db.execute(query)
    dismissal_requests = result.scalars().all()

    # Build response
    requests = []
    for request in dismissal_requests:
        requests.append(
            {
                "id": str(request.id),
                "workspace_id": str(request.workspace_id),
                "review_comment_id": str(request.review_comment_id),
                "requested_by": str(request.requested_by),
                "reason": request.reason,
                "status": request.status,
                "resolved_by": (
                    str(request.resolved_by) if request.resolved_by else None
                ),
                "resolved_at": (
                    request.resolved_at.isoformat() if request.resolved_at else None
                ),
                "created_at": request.created_at.isoformat(),
                "updated_at": request.updated_at.isoformat(),
            }
        )

    return requests


@router.patch("/{request_id}/approve", response_model=dict)
async def approve_dismissal_request(
    request_id: UUID = Path(...),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Approve a dismissal request.

    Only users in the REVIEW_ROLES (REVIEWER, ORG_ADMIN, PLATFORM_ADMIN) can approve dismissal requests.
    """
    # Get the dismissal request
    result = await db.execute(
        select(DismissalRequest).where(DismissalRequest.id == request_id)
    )
    dismissal_request = result.scalar_one_or_none()

    if not dismissal_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dismissal request not found"
        )

    # Check if request is already resolved
    if dismissal_request.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dismissal request is already {dismissal_request.status.lower()}",
        )

    # Approving is a REVIEWER+ action (REVIEW_ROLES, §2.3) in the request's
    # workspace — unknown workspace / non-member → 404, under-role → 403.
    await check_permission_in_workspace(
        db, current_user, dismissal_request.workspace_id, "review"
    )

    # State check (§2.5): dismissal actions are blocked once the review is
    # posted — the finding can no longer change on GitHub.
    comment_result = await db.execute(
        select(ReviewComment).where(
            ReviewComment.id == dismissal_request.review_comment_id
        )
    )
    comment = comment_result.scalar_one_or_none()

    if comment is not None:
        review_result = await db.execute(
            select(Review).where(Review.id == comment.review_id)
        )
        review = review_result.scalar_one_or_none()
        if review is not None and review.posted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Review already posted",
            )

        # Self-review rule (§2.5): no approving your own PR's findings in a
        # multi-member ORG workspace.
        pr_result = await db.execute(
            select(PullRequest).where(PullRequest.id == review.pull_request_id)
        )
        pr = pr_result.scalar_one_or_none()
        if pr is not None and await self_review_blocked(
            db, dismissal_request.workspace_id, pr.author_login, current_user
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot approve findings on a pull request you authored",
            )

    # Approve the request
    dismissal_request.status = "APPROVED"
    dismissal_request.resolved_by = current_user.id
    from datetime import datetime, timezone

    dismissal_request.resolved_at = datetime.now(timezone.utc)

    # If approved, also dismiss the comment (set dismissed = True)
    comment_result = await db.execute(
        select(ReviewComment).where(
            ReviewComment.id == dismissal_request.review_comment_id
        )
    )
    comment = comment_result.scalar_one_or_none()

    if comment:
        comment.dismissed = True
        comment.dismissed_by = current_user.id
        comment.dismissed_at = dismissal_request.resolved_at

    await db.commit()
    await db.refresh(dismissal_request)

    return {
        "id": str(dismissal_request.id),
        "workspace_id": str(dismissal_request.workspace_id),
        "review_comment_id": str(dismissal_request.review_comment_id),
        "requested_by": str(dismissal_request.requested_by),
        "reason": dismissal_request.reason,
        "status": dismissal_request.status,
        "resolved_by": str(dismissal_request.resolved_by),
        "resolved_at": (
            dismissal_request.resolved_at.isoformat()
            if dismissal_request.resolved_at
            else None
        ),
        "created_at": dismissal_request.created_at.isoformat(),
        "updated_at": dismissal_request.updated_at.isoformat(),
    }


@router.patch("/{request_id}/reject", response_model=dict)
async def reject_dismissal_request(
    request_id: UUID = Path(...),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Reject a dismissal request.

    Only users in the REVIEW_ROLES (REVIEWER, ORG_ADMIN, PLATFORM_ADMIN) can reject dismissal requests.
    """
    # Get the dismissal request
    result = await db.execute(
        select(DismissalRequest).where(DismissalRequest.id == request_id)
    )
    dismissal_request = result.scalar_one_or_none()

    if not dismissal_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dismissal request not found"
        )

    # Check if request is already resolved
    if dismissal_request.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dismissal request is already {dismissal_request.status.lower()}",
        )

    # Rejecting is a REVIEWER+ action (REVIEW_ROLES, §2.3) in the request's
    # workspace — unknown workspace / non-member → 404, under-role → 403.
    await check_permission_in_workspace(
        db, current_user, dismissal_request.workspace_id, "review"
    )

    # Reject the request
    dismissal_request.status = "REJECTED"
    dismissal_request.resolved_by = current_user.id
    from datetime import datetime, timezone

    dismissal_request.resolved_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(dismissal_request)

    return {
        "id": str(dismissal_request.id),
        "workspace_id": str(dismissal_request.workspace_id),
        "review_comment_id": str(dismissal_request.review_comment_id),
        "requested_by": str(dismissal_request.requested_by),
        "reason": dismissal_request.reason,
        "status": dismissal_request.status,
        "resolved_by": str(dismissal_request.resolved_by),
        "resolved_at": (
            dismissal_request.resolved_at.isoformat()
            if dismissal_request.resolved_at
            else None
        ),
        "created_at": dismissal_request.created_at.isoformat(),
        "updated_at": dismissal_request.updated_at.isoformat(),
    }
