"""
Repository Schemas
Request/Response models for repository management.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RepositoryBase(BaseModel):
    """Base repository schema with common fields."""

    name: str = Field(..., max_length=255, description="Repository name")
    full_name: str = Field(..., max_length=512, description="Full name (owner/repo)")
    private: bool = Field(default=False, description="Whether the repository is private")
    default_branch: str = Field(default="main", description="Default branch name")


class RepositoryCreate(RepositoryBase):
    """Schema for creating a new repository."""

    installation_id: str = Field(..., description="GitHub App installation ID")
    github_repo_id: int = Field(..., description="GitHub repository ID")
    webhook_id: Optional[int] = Field(None, description="GitHub webhook ID")


class RepositoryUpdate(BaseModel):
    """Schema for updating repository information."""

    enabled: Optional[bool] = Field(None, description="Whether CodeSage is enabled")
    default_branch: Optional[str] = Field(None, description="Default branch name")


class RepositorySettings(BaseModel):
    """Repository-specific CodeSage settings."""

    auto_review: bool = Field(default=True, description="Auto-trigger review on PR")
    review_on_push: bool = Field(default=False, description="Review on push to PR")
    notify_on_failure: bool = Field(default=True, description="Notify on review failure")
    max_files_per_review: int = Field(default=50, ge=1, le=200, description="Max files per review")


class RepositoryResponse(BaseModel):
    """Repository response schema."""

    id: str = Field(..., description="Repository UUID")
    installation_id: str = Field(..., description="Installation UUID")
    github_repo_id: int = Field(..., description="GitHub repository ID")
    name: str = Field(..., description="Repository name")
    full_name: str = Field(..., description="Full name (owner/repo)")
    owner: str = Field(default="", description="Repository owner")
    description: Optional[str] = Field(None, description="Repository description")
    private: bool = Field(..., description="Whether the repository is private")
    default_branch: str = Field(..., description="Default branch name")
    language: Optional[str] = Field(None, description="Primary language")
    stars: int = Field(default=0, description="Star count")
    forks: int = Field(default=0, description="Fork count")
    open_issues: int = Field(default=0, description="Open issues count")
    webhook_enabled: bool = Field(default=False, description="Webhook status")
    webhook_id: Optional[int] = Field(None, description="GitHub webhook ID")
    enabled: bool = Field(..., description="Whether CodeSage is enabled")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}

    @field_validator("id", "installation_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    @field_validator("owner", mode="before")
    @classmethod
    def extract_owner(cls, v, info):
        if v:
            return v
        full_name = info.data.get("full_name") if info.data else None
        if full_name:
            parts = full_name.split("/", 1)
            return parts[0] if len(parts) > 1 else ""
        return v


class RepositoryListResponse(BaseModel):
    """Paginated list of repositories."""

    items: list[RepositoryResponse] = Field(..., description="List of repositories")
    total: int = Field(..., description="Total count")
    page: int = Field(..., description="Current page")
    per_page: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total pages")


class RepositoryDetail(RepositoryResponse):
    """Detailed repository information with settings."""

    settings: RepositorySettings = Field(..., description="Repository settings")
    total_prs: int = Field(default=0, description="Total pull requests")
    total_reviews: int = Field(default=0, description="Total reviews completed")