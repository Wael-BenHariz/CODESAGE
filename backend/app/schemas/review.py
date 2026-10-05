"""
Review Schemas
Request/Response models for code review management.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.services.review_posting import EDITED_SUMMARY_MAX_CHARS


class _OrmUuidMixin(BaseModel):
    """Accept ``uuid.UUID`` values for the ``str`` id fields.

    ORM rows carry UUID column values and Pydantic v2 refuses to coerce
    UUID → ``str``, so plain ``model_validate(row)`` (``from_attributes``)
    used to raise a ValidationError — which made every list endpoint that
    validates rows directly return 500. The before-validator normalizes
    any UUID to its canonical string; plain string/JSON input passes
    through unchanged.
    """

    @model_validator(mode="before")
    @classmethod
    def _stringify_uuids(cls, data: object) -> object:
        if not isinstance(data, dict):
            # ORM object (from_attributes): collect the declared fields.
            data = {
                name: getattr(data, name)
                for name in cls.model_fields
                if hasattr(data, name)
            }
        return {
            name: str(value) if isinstance(value, UUID) else value
            for name, value in data.items()
        }


class ReviewBase(BaseModel):
    """Base review schema with common fields."""

    pull_request_id: str = Field(..., description="Pull request UUID")


class ReviewCreate(ReviewBase):
    """Schema for creating a new review."""

    user_id: str | None = Field(None, description="User who triggered the review")
    config: dict | None = Field(None, description="Review configuration options")


class ReviewUpdate(BaseModel):
    """Schema for updating review information."""

    status: str | None = Field(None, description="Review status")
    summary: str | None = Field(None, description="Review summary")


class SummaryUpdate(BaseModel):
    """Request body for ``PATCH /reviews/{review_id}/summary`` (plan Step 7).

    Writes ``reviews.edited_summary`` — the base of the staged GitHub
    body (Q3). Capped at ``EDITED_SUMMARY_MAX_CHARS`` (60 000): the cap
    lives with the body builder so both stay in lockstep.
    """

    summary: str = Field(
        ...,
        max_length=EDITED_SUMMARY_MAX_CHARS,
        description=(
            "Human-edited staged summary (GitHub markdown), max "
            f"{EDITED_SUMMARY_MAX_CHARS} characters"
        ),
    )


class ValidationCreate(BaseModel):
    """Request body for ``PATCH /reviews/{id}/comments/{id}/validate``.

    Upserts the caller's verdict (unique per comment + reviewer, plan
    Step 9). The ``Literal`` enums match the migration 016 CHECK
    constraints, so unknown values are rejected 422 before touching
    the database.
    """

    verdict: Literal["confirmed", "false_positive", "needs_investigation"] = Field(
        ..., description="The reviewer's verdict"
    )
    severity_override: Literal["info", "warning", "error", "suggestion"] | None = Field(
        None, description="Reviewer-assigned severity; NULL keeps the original"
    )
    note: str | None = Field(
        None, description="Plain-text justification — stored as-is, never parsed"
    )


class CommentValidation(BaseModel):
    """One reviewer's verdict on a finding (plan Step 9).

    Attached to ``ReviewCommentResponse.validations`` — one row per
    reviewer (newest first), so the UI can show who judged the finding,
    what they decided, and when.
    """

    verdict: str = Field(
        ..., description="confirmed | false_positive | needs_investigation"
    )
    severity_override: str | None = Field(
        None, description="Reviewer-assigned severity; NULL keeps the original"
    )
    note: str | None = Field(None, description="Plain-text justification")
    reviewer_login: str = Field(..., description="Login of the verdict's author")
    created_at: datetime = Field(..., description="When the verdict was first given")
    updated_at: datetime = Field(..., description="When the verdict last changed")

    model_config = {"from_attributes": True}


class ReviewStatus(BaseModel):
    """Review status information."""

    review_id: str = Field(..., description="Review UUID")
    status: str = Field(
        ..., description="Status: pending, processing, completed, failed"
    )
    progress: float | None = Field(
        None, ge=0, le=100, description="Progress percentage"
    )
    started_at: datetime = Field(..., description="When processing started")
    completed_at: datetime | None = Field(None, description="When processing completed")
    error_message: str | None = Field(None, description="Error if failed")


class ReviewResponse(_OrmUuidMixin):
    """Review response schema."""

    id: str = Field(..., description="Review UUID")
    pull_request_id: str = Field(..., description="Pull request UUID")
    user_id: str | None = Field(None, description="User UUID who triggered the review")
    status: str = Field(..., description="Review status")
    error_message: str | None = Field(None, description="Error message if failed")
    summary: str | None = Field(None, description="Review summary")
    # Staged posting (Step 6/7) — additive so old clients keep working.
    posting_mode: str = Field("auto", description="Org posting mode: auto | staged")
    posted_at: datetime | None = Field(
        None, description="GitHub post time (null = never)"
    )
    edited_summary: str | None = Field(
        None, description="Human-edited staged summary (wins over summary)"
    )
    github_review_id: int | None = Field(None, description="GitHub review ID if posted")
    overall_severity: str | None = Field(None, description="Overall severity verdict")
    gemini_model: str | None = Field(None, description="AI model used")
    tokens_used: int | None = Field(None, description="Tokens consumed")
    started_at: datetime = Field(..., description="Start timestamp")
    completed_at: datetime | None = Field(None, description="Completion timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class ReviewListResponse(BaseModel):
    """Paginated list of reviews."""

    items: list[ReviewResponse] = Field(..., description="List of reviews")
    total: int = Field(..., description="Total count")
    page: int = Field(..., description="Current page")
    per_page: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total pages")


class ReviewWithComments(ReviewResponse):
    """Review with associated comments."""

    comments_count: int = Field(default=0, description="Number of comments")
    comments: list["ReviewCommentResponse"] = Field(
        default_factory=list, description="Review comments"
    )
    # Caller's effective role in this review's org (Step 7b) — the UI uses
    # it to show/hide elevation-dependent controls (cosmetic only; every
    # write is re-checked server-side by the route guard).
    viewer_role: str = Field(
        ...,
        description="Effective role of the caller in the review's org",
    )


class ReviewCommentResponse(_OrmUuidMixin):
    """Review comment response schema."""

    id: str = Field(..., description="Comment UUID")
    review_id: str = Field(..., description="Review UUID")
    pull_request_id: str = Field(..., description="Pull request UUID")
    github_comment_id: int | None = Field(None, description="GitHub comment ID")
    file_path: str = Field(..., description="File path")
    line_number: int | None = Field(None, description="Line number")
    body: str = Field(..., description="Comment body")
    severity: str = Field(..., description="Severity: info, warning, error, suggestion")
    category: str = Field(
        ..., description="Category: bug, security, performance, style, etc."
    )
    resolved: bool = Field(..., description="Whether resolved")
    resolved_at: datetime | None = Field(None, description="Resolution timestamp")
    # Staged posting (Step 6/7): dismissal excludes the finding from the
    # GitHub Findings body. Defaults keep pre-014 payloads compatible.
    dismissed: bool = Field(False, description="Excluded from staged Findings")
    dismissed_by: str | None = Field(None, description="User UUID who dismissed")
    dismissed_at: datetime | None = Field(None, description="Dismissal timestamp")
    # Source-finding enrichment (Step 7b, migration 015): NULL when the
    # worker could not match this comment to a finding or the comment
    # predates 015 — the panel renders without tool/rule/snippet then.
    tool: str | None = Field(None, description="Tool of the matched finding")
    rule_id: str | None = Field(None, description="Rule id of the matched finding")
    cwe: list[str] | None = Field(None, description="CWE ids of the matched finding")
    line_start: int | None = Field(
        None, description="First line of the matched finding's range"
    )
    line_end: int | None = Field(
        None, description="Last line of the matched finding's range"
    )
    snippet: str | None = Field(
        None, description="Source excerpt of the matched finding"
    )
    also_detected_by: list[str] | None = Field(
        None, description="Other tools that found the same defect"
    )
    # Reviewer verdicts (Step 9, migration 016): newest first, one row
    # per reviewer; empty until someone judges the finding.
    validations: list[CommentValidation] = Field(
        default_factory=list, description="Reviewer verdicts on this finding"
    )
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class ReviewSummary(BaseModel):
    """Summary of a code review."""

    total_files_reviewed: int = Field(..., description="Number of files reviewed")
    total_comments: int = Field(..., description="Total comments generated")
    issues_by_severity: dict[str, int] = Field(
        ..., description="Issues grouped by severity"
    )
    issues_by_category: dict[str, int] = Field(
        ..., description="Issues grouped by category"
    )
    processing_time_seconds: float = Field(
        ..., description="Time taken to complete review"
    )


# Update forward reference
ReviewWithComments.model_rebuild()
