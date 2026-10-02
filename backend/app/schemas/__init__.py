"""
Pydantic Schemas Package
Request/Response models for API validation and serialization.
"""

from app.schemas.auth import (
    OAuthState,
    Token,
    TokenPayload,
)
from app.schemas.llm_settings import (
    LLMSettingsResponse,
    LLMSettingsUpdate,
    LLMTestResponse,
)
from app.schemas.pull_request import (
    PullRequestBase,
    PullRequestCreate,
    PullRequestListResponse,
    PullRequestResponse,
    PullRequestWithReviews,
)
from app.schemas.repository import (
    RepositoryBase,
    RepositoryCreate,
    RepositoryListResponse,
    RepositoryResponse,
    RepositorySettings,
    RepositoryUpdate,
)
from app.schemas.review import (
    ReviewBase,
    ReviewCreate,
    ReviewListResponse,
    ReviewResponse,
    ReviewStatus,
    ReviewWithComments,
)
from app.schemas.scan_report import ScanReportResponse
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.schemas.webhook import (
    GitHubWebhookPayload,
    WebhookEventBase,
    WebhookEventListResponse,
    WebhookEventResponse,
)

__all__ = [
    "GitHubWebhookPayload",
    # LLM Settings
    "LLMSettingsResponse",
    "LLMSettingsUpdate",
    "LLMTestResponse",
    "OAuthState",
    # Pull Request
    "PullRequestBase",
    "PullRequestCreate",
    "PullRequestListResponse",
    "PullRequestResponse",
    "PullRequestWithReviews",
    # Repository
    "RepositoryBase",
    "RepositoryCreate",
    "RepositoryListResponse",
    "RepositoryResponse",
    "RepositorySettings",
    "RepositoryUpdate",
    # Review
    "ReviewBase",
    "ReviewCreate",
    "ReviewListResponse",
    "ReviewResponse",
    "ReviewStatus",
    "ReviewWithComments",
    # Scan report (unified static analysis)
    "ScanReportResponse",
    # Auth
    "Token",
    "TokenPayload",
    # User
    "UserBase",
    "UserCreate",
    "UserListResponse",
    "UserResponse",
    "UserUpdate",
    # Webhook
    "WebhookEventBase",
    "WebhookEventListResponse",
    "WebhookEventResponse",
]
