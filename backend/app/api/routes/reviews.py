"""
Review Routes
Review status and comment management endpoints.

Org-scoped (plan Step 7 / flag F3): every route here resolves the
review's org through ``review -> PR -> repo -> installation -> org`` and
applies the §2 capability model — cross-org callers get the same 404 as
an unknown id. The staged-posting mutations (summary edit, dismiss,
restore, post) additionally carry the F2 carve-out: PLATFORM_ADMIN must
be an org member too.
"""

from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    PullRequest,
    Repository,
    Review,
    ReviewComment,
    ReviewFindingValidation,
    ScanFindingRow,
    ScanReportRow,
    User,
)
from app.schemas.review import (
    CommentValidation,
    ReviewCommentResponse,
    ReviewListResponse,
    ReviewResponse,
    ReviewStatus,
    ReviewWithComments,
    SummaryUpdate,
    ValidationCreate,
)
from app.schemas.scan_report import ScanReportResponse
from app.security.dependencies import get_current_user
from app.security.org_access import ReviewAccess, require_review_access
from app.security.roles import (
    ROLE_DEVELOPER,
    ROLE_PLATFORM_ADMIN,
    ROLE_REVIEWER,
    require_developer,
)
from app.services.review_posting import ReviewPostError, post_review_to_github
from app.services.scan_report_store import finding_from_row

router = APIRouter()

# Scan-report filter vocabularies (mirrors the schema's literals).
_SCAN_TOOLS = ("sonarqube", "semgrep")
_SCAN_SEVERITIES = ("info", "low", "medium", "high", "critical")
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# starlette >= 1.x renamed HTTP_422_UNPROCESSABLE_ENTITY (accessing the old
# name emits a deprecation warning on every call); 422 for older versions.
_UNPROCESSABLE_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

# Review-scoped guards (plan §2 capability model, Step 7):
#   reads            → org member; PLATFORM_ADMIN may bypass membership (F2)
#   legacy mutations → member (require_developer stacked for parity) with the
#                      same read-style bypass (§3 retrofit row)
#   staged mutations → member + effective ≥ DEVELOPER and NO PLATFORM_ADMIN
#                      bypass (F2 carve-out: summary edit / dismiss / restore /
#                      post — a platform admin must be an org member to touch
#                      a customer's PR)
_review_reader = require_review_access(ROLE_DEVELOPER, write=False)
_review_member_write = require_review_access(ROLE_DEVELOPER, write=True)
_review_writer = require_review_access(
    ROLE_DEVELOPER, write=True, platform_admin_bypass=False
)
# Verdict upsert (Step 9): member + effective >= REVIEWER and NO
# PLATFORM_ADMIN bypass — validate is in the F2 carve-out list too.
_review_comment_validator = require_review_access(
    ROLE_REVIEWER, write=True, platform_admin_bypass=False
)


@router.get("", response_model=ReviewListResponse)
async def list_reviews(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    status_filter: str | None = Query(None, description="Filter by status"),
    pull_request_id: str | None = Query(None, description="Filter by pull request"),
):
    """
    List reviews visible to the caller.

    Org-scoped (flag F3): a member sees the reviews of their orgs;
    PLATFORM_ADMIN sees everything. Reviews whose repo never got an org
    row are visible to nobody else (see scripts/review_access_precheck.py).
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

    # F3 retrofit: org membership filter — reviews whose PR chains into an
    # org the caller belongs to. PLATFORM_ADMIN bypasses (F2 read).
    if current_user.role != ROLE_PLATFORM_ADMIN:
        member_org_prs = (
            select(PullRequest.id)
            .join(Repository, Repository.id == PullRequest.repository_id)
            .join(
                GitHubInstallation,
                GitHubInstallation.id == Repository.installation_id,
            )
            .join(Org, Org.installation_id == GitHubInstallation.installation_id)
            .join(
                OrgMember,
                and_(
                    OrgMember.org_id == Org.id,
                    OrgMember.user_id == current_user.id,
                ),
            )
        )
        query = query.where(Review.pull_request_id.in_(member_org_prs))
        count_query = count_query.where(Review.pull_request_id.in_(member_org_prs))

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
    db: AsyncSession = Depends(get_db),  # noqa: B008
    access: ReviewAccess = Depends(_review_reader),  # noqa: B008
):
    """
    Get review by ID with all comments.

    Org-scoped (flag F3): unknown id and cross-org both 404 with the
    same detail. ``comments`` carry the ``dismissed*`` flags so the
    staged posting panel can mark excluded findings, plus the Step 7b
    source-finding enrichment columns (tool/rule/cwe/lines/snippet/
    also_detected_by — NULL when unmatched or pre-015). ``viewer_role``
    is the caller's effective role in the review's org.
    """
    review = access.review  # already loaded (and authorized) by the guard

    return ReviewWithComments(
        id=str(review.id),
        pull_request_id=str(review.pull_request_id),
        user_id=str(review.user_id) if review.user_id else None,
        status=review.status,
        error_message=review.error_message,
        summary=review.summary,
        posting_mode=review.posting_mode,
        posted_at=review.posted_at,
        edited_summary=review.edited_summary,
        github_review_id=review.github_review_id,
        overall_severity=review.overall_severity,
        gemini_model=review.gemini_model,
        tokens_used=review.tokens_used,
        started_at=review.started_at,
        completed_at=review.completed_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
        comments_count=len(review.comments),
        viewer_role=access.effective_role,
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
                dismissed=c.dismissed,
                dismissed_by=str(c.dismissed_by) if c.dismissed_by else None,
                dismissed_at=c.dismissed_at,
                tool=c.tool,
                rule_id=c.rule_id,
                cwe=list(c.cwe) if c.cwe is not None else None,
                line_start=c.line_start,
                line_end=c.line_end,
                snippet=c.snippet,
                also_detected_by=(
                    list(c.also_detected_by) if c.also_detected_by is not None else None
                ),
                # Step 9 verdicts (selectin-loaded, newest first).
                validations=[
                    CommentValidation.model_validate(v) for v in c.validations
                ],
                created_at=c.created_at,
            )
            for c in review.comments
        ],
    )


@router.get("/{review_id}/scan-report", response_model=ScanReportResponse)
async def get_scan_report(
    review_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    access: Annotated[ReviewAccess, Depends(_review_reader)],
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

    404 for an unknown review, a cross-org review (flag F3) or a review
    that has no scan report yet; 422 for filter values outside the
    vocabulary. ``summary`` always describes the FULL scan — filters only
    narrow ``findings``.
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

    review = access.review  # loaded and org-checked by the guard (F3)

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
    db: AsyncSession = Depends(get_db),  # noqa: B008
    access: ReviewAccess = Depends(_review_reader),  # noqa: B008
):
    """
    Get review processing status.
    Useful for polling review progress.

    Org-scoped like ``GET /reviews/{review_id}`` (flag F3): unknown id
    and cross-org both 404 with the same detail.
    """
    review = access.review  # loaded and org-checked by the guard

    # Calculate progress
    progress = None
    if review.status == "processing" and review.started_at:
        # Estimate progress based on time (placeholder)
        from datetime import datetime, timezone

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
    db: AsyncSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_developer),  # noqa: B008
    access: ReviewAccess = Depends(_review_member_write),  # noqa: B008
):
    """
    Retry a failed review.

    Org-scoped (flag F3): unknown id and cross-org both 404; NONE is
    rejected 403 by ``require_developer`` first.
    """
    review = access.review  # loaded and org-checked by the guard

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

        await queue_review(review_id, trigger="manual")
    except Exception:  # noqa: BLE001
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
    db: AsyncSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_developer),  # noqa: B008
    access: ReviewAccess = Depends(_review_member_write),  # noqa: B008
):
    """
    Delete a review and its comments.

    Org-scoped (flag F3): unknown id and cross-org both 404.
    """
    review = access.review  # loaded and org-checked by the guard

    await db.delete(review)
    await db.commit()


@router.patch("/{review_id}/comments/{comment_id}/resolve")
async def resolve_comment(
    review_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_developer),  # noqa: B008
    access: ReviewAccess = Depends(_review_member_write),  # noqa: B008
):
    """
    Mark a review comment as resolved.

    Org-scoped (flag F3): a cross-org caller 404s on the review guard
    *before* any comment lookup — an existing comment is never revealed.
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


# --- Staged posting (plan Step 7) --------------------------------------------
# Member + effective >= DEVELOPER on all four, and NO PLATFORM_ADMIN
# bypass (F2 carve-out): a platform admin must be an org member to edit,
# trim or post a customer's review.


@router.patch("/{review_id}/summary")
async def update_review_summary(
    review_id: str,
    payload: SummaryUpdate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    access: ReviewAccess = Depends(_review_writer),  # noqa: B008
):
    """
    Edit the staged summary (``reviews.edited_summary``, plan Q3).

    Allowed only while ``posted_at IS NULL`` — once GitHub has the body
    it is read-only (409). Over-cap payloads are rejected 422 by the
    schema (``EDITED_SUMMARY_MAX_CHARS``).
    """
    review = access.review
    if review.posted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review already posted to GitHub; the summary is read-only",
        )

    review.edited_summary = payload.summary
    await db.commit()

    return {
        "review_id": str(review.id),
        "summary": review.summary,
        "edited_summary": review.edited_summary,
        "status": review.status,
        "posted_at": review.posted_at.isoformat() if review.posted_at else None,
    }


async def _set_comment_dismissed(
    db: AsyncSession,
    access: ReviewAccess,
    comment_id: str,
    *,
    dismissed: bool,
) -> ReviewComment:
    """Shared body of dismiss/restore (idempotent state set, not a toggle)."""
    result = await db.execute(
        select(ReviewComment)
        .where(ReviewComment.id == comment_id)
        .where(ReviewComment.review_id == access.review.id)
    )
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )

    if dismissed:
        comment.dismissed = True
        comment.dismissed_by = access.user.id
        comment.dismissed_at = datetime.now(timezone.utc)
    else:
        comment.dismissed = False
        comment.dismissed_by = None
        comment.dismissed_at = None
    await db.commit()
    return comment


@router.patch("/{review_id}/comments/{comment_id}/dismiss")
async def dismiss_comment(
    review_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    access: ReviewAccess = Depends(_review_writer),  # noqa: B008
):
    """
    Dismiss a finding: it is excluded from the staged ``## Findings``
    body (plan Q3) but stays in the review for auditability.
    """
    comment = await _set_comment_dismissed(db, access, comment_id, dismissed=True)
    return ReviewCommentResponse.model_validate(comment)


@router.patch("/{review_id}/comments/{comment_id}/restore")
async def restore_comment(
    review_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    access: ReviewAccess = Depends(_review_writer),  # noqa: B008
):
    """Undo a dismissal — the finding is back in the staged Findings body."""
    comment = await _set_comment_dismissed(db, access, comment_id, dismissed=False)
    return ReviewCommentResponse.model_validate(comment)


# --- Reviewer validation (plan Step 9) ----------------------------------------


@router.patch("/{review_id}/comments/{comment_id}/validate")
async def validate_comment(
    review_id: str,
    comment_id: str,
    payload: ValidationCreate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    access: ReviewAccess = Depends(_review_comment_validator),  # noqa: B008
):
    """
    Upsert the caller's verdict for one finding (plan Step 9).

    Guard: org member + effective role >= REVIEWER with the F2 carve-out
    (no PLATFORM_ADMIN bypass without a membership row). A changed mind
    replaces the verdict — ``UNIQUE (comment_id, reviewer_id)`` plus
    ``ON CONFLICT ... DO UPDATE``. ``note`` is stored as-is (plain text);
    the frontend renders it through Angular interpolation only.
    """
    # Same comment-ownership check as dismiss/restore: an existing
    # comment of ANOTHER review is never revealed (404 either way).
    result = await db.execute(
        select(ReviewComment)
        .where(ReviewComment.id == comment_id)
        .where(ReviewComment.review_id == access.review.id)
    )
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )

    now = datetime.now(timezone.utc)
    stmt = (
        # pg_insert (dialect form) — the generic Insert has no
        # on_conflict_do_update.
        pg_insert(ReviewFindingValidation)
        .values(
            comment_id=comment.id,
            reviewer_id=access.user.id,
            verdict=payload.verdict,
            severity_override=payload.severity_override,
            note=payload.note,
        )
        .on_conflict_do_update(
            index_elements=["comment_id", "reviewer_id"],
            set_={
                "verdict": payload.verdict,
                "severity_override": payload.severity_override,
                "note": payload.note,
                "updated_at": now,
            },
        )
        .returning(
            ReviewFindingValidation.created_at,
            ReviewFindingValidation.updated_at,
        )
    )
    row = (await db.execute(stmt)).one()
    await db.commit()

    return CommentValidation(
        verdict=payload.verdict,
        severity_override=payload.severity_override,
        note=payload.note,
        reviewer_login=access.user.login,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/{review_id}/post")
async def post_review_now(
    review_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    access: ReviewAccess = Depends(_review_writer),  # noqa: B008
):
    """
    Post a staged review to GitHub now (plan Step 7).

    Race-safe: the row is re-read under ``FOR UPDATE``, so a double click
    serializes — the second request observes ``posted_at`` and gets 409.
    Preconditions (checked inside the lock): ``posting_mode == "staged"``,
    not yet posted, ``status == "ready_to_post"`` — each a 409. On a
    GitHub failure nothing is posted (``posted_at`` stays NULL), the
    error detail is persisted to ``error_message`` and the lock is
    released before answering 502, so the call is retryable.
    """
    # populate_existing: the guard already loaded this row into the
    # identity map (plain SELECT) — without it the FOR UPDATE statement
    # would fetch the fresh row but hand back the STALE instance, letting
    # a concurrent second request pass the posted_at pre-check.
    result = await db.execute(
        select(Review)
        .where(Review.id == review_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    review = result.scalar_one_or_none()
    if review is None:  # deleted between guard and lock
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    if review.posting_mode != "staged":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Review is not staged for manual posting "
                f"(posting_mode={review.posting_mode!r}); "
                "the worker posts it automatically"
            ),
        )
    if review.posted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review already posted to GitHub",
        )
    if review.status != "ready_to_post":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Review is not ready to post (status={review.status!r}); "
                "wait for the worker to finish"
            ),
        )

    try:
        github_review_id = await post_review_to_github(db, review)
    except ReviewPostError as exc:
        detail = (
            f"GitHub post failed ({exc.status_code}): {exc.detail[:800]} — "
            "nothing was posted, retry after fixing the cause"
        )
        review.error_message = detail
        await db.commit()  # persists the stored detail and releases the lock
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    except httpx.HTTPError as exc:
        detail = (
            f"GitHub post failed ({type(exc).__name__}: {exc}) — "
            "nothing was posted, retry after fixing the cause"
        )
        review.error_message = detail
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    posted_at = datetime.now(timezone.utc)
    updated = await db.execute(
        update(Review)
        .where(Review.id == review.id, Review.posted_at.is_(None))
        .values(
            # Same terminal state as the worker's automatic post: a review
            # GitHub already has is completed, never "ready_to_post" again.
            status="completed",
            posted_at=posted_at,
            github_review_id=github_review_id,
            error_message=None,
        )
        .returning(Review.id)
    )
    if updated.scalar_one_or_none() is None:  # lost the race after the lock
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review already posted to GitHub",
        )
    await db.commit()

    return {
        "review_id": str(review_id),
        "github_review_id": github_review_id,
        "posted_at": posted_at.isoformat(),
        "message": "Review posted to GitHub",
    }
