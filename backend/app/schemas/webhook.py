"""
Webhook Schemas
Request/Response models for GitHub webhook handling.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class WebhookEventBase(BaseModel):
    """Base webhook event schema."""

    event_type: str = Field(..., description="GitHub event type")
    delivery_id: str = Field(..., description="GitHub delivery ID")
    action: str = Field(..., description="Event action")


class WebhookEventCreate(WebhookEventBase):
    """Schema for creating a webhook event."""

    repository_id: str = Field(..., description="Repository UUID")
    payload: dict[str, Any] = Field(..., description="Full webhook payload")


class WebhookEventResponse(BaseModel):
    """Webhook event response schema."""

    id: str = Field(..., description="Event UUID")
    repository_id: str = Field(..., description="Repository UUID")
    event_type: str = Field(..., description="Event type")
    delivery_id: str = Field(..., description="Delivery ID")
    action: str = Field(..., description="Event action")
    processed: bool = Field(..., description="Whether processed")
    created_at: datetime = Field(..., description="Delivery timestamp")

    model_config = {"from_attributes": True}


class WebhookEventListResponse(BaseModel):
    """Paginated list of webhook events."""

    items: list[WebhookEventResponse] = Field(..., description="List of events")
    total: int = Field(..., description="Total count")
    page: int = Field(..., description="Current page")
    per_page: int = Field(..., description="Items per page")


class WebhookProcessResult(BaseModel):
    """Result of webhook processing."""

    event_id: str = Field(..., description="Event UUID")
    processed: bool = Field(..., description="Whether successfully processed")
    action_taken: Optional[str] = Field(None, description="Action taken (e.g., 'created_review')")
    review_id: Optional[str] = Field(None, description="Review UUID if a review was created")
    error: Optional[str] = Field(None, description="Error message if failed")


class GitHubWebhookPayload(BaseModel):
    """Parsed GitHub webhook payload for pull_request events."""

    action: str = Field(..., description="Action that triggered the event")
    number: int = Field(..., description="PR number")
    pull_request: dict[str, Any] = Field(..., description="Pull request data")
    repository: dict[str, Any] = Field(..., description="Repository data")
    sender: dict[str, Any] = Field(..., description="User who triggered the event")
    installation: Optional[dict[str, Any]] = Field(None, description="GitHub App installation")


class PullRequestWebhookData(BaseModel):
    """Simplified PR data extracted from webhook."""

    github_pr_id: int
    number: int
    title: str
    body: Optional[str]
    state: str
    author_login: str
    author_avatar_url: Optional[str]
    base_branch: str
    head_branch: str
    base_sha: str
    head_sha: str
    additions: int
    deletions: int
    changed_files: int


class InstallationAction(BaseModel):
    """GitHub App installation action."""

    action: str = Field(..., description="Action: created, deleted, suspended, unsuspended")
    installation: dict[str, Any] = Field(..., description="Installation data")
    sender: dict[str, Any] = Field(..., description="User who performed the action")