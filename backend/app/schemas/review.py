"""
Review Schemas
Request/Response models for code review management.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReviewBase(BaseModel):
    """Base review schema with common fields."""

    pull_request_id: str = Field(..., description="Pull request UUID")


class ReviewCreate(ReviewBase):
    """Schema for creating a new review."""

    user_id: Optional[str] = Field(None, description="User who triggered the review")
    config: Optional[dict] = Field(None, description="Review configuration options")


class ReviewUpdate(BaseModel):
    """Schema for updating review information."""

    status: Optional[str] = Field(None, description="Review status")
    summary: Optional[str] = Field(None, description="Review summary")


class ReviewStatus(BaseModel):
    """Review status information."""

    review_id: str = Field(..., description="Review UUID")
    status: str = Field(..., description="Status: pending, processing, completed, failed")
    progress: Optional[float] = Field(None, ge=0, le=100, description="Progress percentage")
    started_at: datetime = Field(..., description="When processing started")
    completed_at: Optional[datetime] = Field(None, description="When processing completed")
    error_message: Optional[str] = Field(None, description="Error if failed")


class ReviewResponse(BaseModel):
    """Review response schema."""

    id: str = Field(..., description="Review UUID")
    pull_request_id: str = Field(..., description="Pull request UUID")
    user_id: Optional[str] = Field(None, description="User UUID who triggered the review")
    status: str = Field(..., description="Review status")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    summary: Optional[str] = Field(None, description="Review summary")
    gemini_model: Optional[str] = Field(None, description="AI model used")
    tokens_used: Optional[int] = Field(None, description="Tokens consumed")
    started_at: datetime = Field(..., description="Start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
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
    comments: list["ReviewCommentResponse"] = Field(default_factory=list, description="Review comments")


class ReviewCommentResponse(BaseModel):
    """Review comment response schema."""

    id: str = Field(..., description="Comment UUID")
    review_id: str = Field(..., description="Review UUID")
    pull_request_id: str = Field(..., description="Pull request UUID")
    github_comment_id: Optional[int] = Field(None, description="GitHub comment ID")
    file_path: str = Field(..., description="File path")
    line_number: Optional[int] = Field(None, description="Line number")
    body: str = Field(..., description="Comment body")
    severity: str = Field(..., description="Severity: info, warning, error, suggestion")
    category: str = Field(..., description="Category: bug, security, performance, style, etc.")
    resolved: bool = Field(..., description="Whether resolved")
    resolved_at: Optional[datetime] = Field(None, description="Resolution timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class ReviewSummary(BaseModel):
    """Summary of a code review."""

    total_files_reviewed: int = Field(..., description="Number of files reviewed")
    total_comments: int = Field(..., description="Total comments generated")
    issues_by_severity: dict[str, int] = Field(..., description="Issues grouped by severity")
    issues_by_category: dict[str, int] = Field(..., description="Issues grouped by category")
    processing_time_seconds: float = Field(..., description="Time taken to complete review")


# Update forward reference
ReviewWithComments.model_rebuild()