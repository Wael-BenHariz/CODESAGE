"""
Pydantic Schemas Package
Request/Response models for API validation and serialization.
"""

from app.schemas.auth import (
    Token,
    TokenPayload,
    OAuthState,
)
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
)
from app.schemas.repository import (
    RepositoryBase,
    RepositoryCreate,
    RepositoryUpdate,
    RepositoryResponse,
    RepositoryListResponse,
    RepositorySettings,
)
from app.schemas.pull_request import (
    PullRequestBase,
    PullRequestCreate,
    PullRequestResponse,
    PullRequestListResponse,
    PullRequestWithReviews,
)
from app.schemas.review import (
    ReviewBase,
    ReviewCreate,
    ReviewResponse,
    ReviewWithComments,
    ReviewStatus,
    ReviewListResponse,
)
from app.schemas.webhook import (
    WebhookEventBase,
    WebhookEventResponse,
    WebhookEventListResponse,
    GitHubWebhookPayload,
)

__all__ = [
    # Auth
    "Token",
    "TokenPayload",
    "OAuthState",
    # User
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserListResponse",
    # Repository
    "RepositoryBase",
    "RepositoryCreate",
    "RepositoryUpdate",
    "RepositoryResponse",
    "RepositoryListResponse",
    "RepositorySettings",
    # Pull Request
    "PullRequestBase",
    "PullRequestCreate",
    "PullRequestResponse",
    "PullRequestListResponse",
    "PullRequestWithReviews",
    # Review
    "ReviewBase",
    "ReviewCreate",
    "ReviewResponse",
    "ReviewWithComments",
    "ReviewStatus",
    "ReviewListResponse",
    # Webhook
    "WebhookEventBase",
    "WebhookEventResponse",
    "WebhookEventListResponse",
    "GitHubWebhookPayload",
]