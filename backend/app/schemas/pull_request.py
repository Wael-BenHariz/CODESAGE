"""
Pull Request Schemas
Request/Response models for pull request management.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PullRequestBase(BaseModel):
    """Base pull request schema with common fields."""

    number: int = Field(..., description="PR number within the repository")
    title: str = Field(..., max_length=500, description="PR title")
    state: str = Field(default="open", description="PR state: open, closed, merged")
    base_branch: str = Field(..., description="Target branch name")
    head_branch: str = Field(..., description="Source branch name")


class PullRequestCreate(PullRequestBase):
    """Schema for creating/updating a pull request."""

    repository_id: str = Field(..., description="Repository UUID")
    github_pr_id: int = Field(..., description="GitHub pull request ID")
    body: Optional[str] = Field(None, description="PR description body")
    author_login: str = Field(..., description="GitHub username of PR author")
    author_avatar_url: Optional[str] = Field(None, description="Avatar URL of PR author")
    base_sha: str = Field(..., max_length=40, description="SHA of the base commit")
    head_sha: str = Field(..., max_length=40, description="SHA of the head commit")
    additions: int = Field(default=0, ge=0, description="Number of lines added")
    deletions: int = Field(default=0, ge=0, description="Number of lines deleted")
    changed_files: int = Field(default=0, ge=0, description="Number of files changed")


class PullRequestUpdate(BaseModel):
    """Schema for updating pull request information."""

    title: Optional[str] = Field(None, max_length=500, description="PR title")
    body: Optional[str] = Field(None, description="PR description body")
    state: Optional[str] = Field(None, description="PR state: open, closed, merged")
    base_sha: Optional[str] = Field(None, max_length=40, description="SHA of the base commit")
    head_sha: Optional[str] = Field(None, max_length=40, description="SHA of the head commit")
    additions: Optional[int] = Field(None, ge=0, description="Number of lines added")
    deletions: Optional[int] = Field(None, ge=0, description="Number of lines deleted")
    changed_files: Optional[int] = Field(None, ge=0, description="Number of files changed")


class PullRequestResponse(BaseModel):
    """Pull request response schema."""

    id: str = Field(..., description="Pull request UUID")
    repository_id: str = Field(..., description="Repository UUID")
    github_pr_id: int = Field(..., description="GitHub pull request ID")
    number: int = Field(..., description="PR number")
    title: str = Field(..., description="PR title")
    body: Optional[str] = Field(None, description="PR description body")
    state: str = Field(..., description="PR state")
    author_login: str = Field(..., description="GitHub username of author")
    author_avatar_url: Optional[str] = Field(None, description="Avatar URL of author")
    base_branch: str = Field(..., description="Target branch")
    head_branch: str = Field(..., description="Source branch")
    base_sha: str = Field(..., description="Base commit SHA")
    head_sha: str = Field(..., description="Head commit SHA")
    additions: int = Field(..., description="Lines added")
    deletions: int = Field(..., description="Lines deleted")
    changed_files: int = Field(..., description="Files changed")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class PullRequestListResponse(BaseModel):
    """Paginated list of pull requests."""

    items: list[PullRequestResponse] = Field(..., description="List of pull requests")
    total: int = Field(..., description="Total count")
    page: int = Field(..., description="Current page")
    per_page: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total pages")


class PullRequestWithReviews(PullRequestResponse):
    """Pull request with associated reviews."""

    reviews_count: int = Field(default=0, description="Number of reviews")
    latest_review_id: Optional[str] = Field(None, description="Latest review UUID")
    latest_review_status: Optional[str] = Field(None, description="Latest review status")


class AuthorInfo(BaseModel):
    """Pull request author information."""

    login: str
    avatar_url: Optional[str] = None


class PRFileChange(BaseModel):
    """File changed in a pull request."""

    filename: str
    status: str  # added, modified, removed, renamed
    additions: int
    deletions: int
    changes: int
    patch: Optional[str] = None
    contents_url: str