"""Database package with models, base, and session management."""

from app.db.base import Base, metadata, utc_now
from app.db.models import (
    GitHubInstallation,
    OAuthToken,
    PullRequest,
    Repository,
    Review,
    ReviewComment,
    User,
    WebhookEvent,
)
from app.db.session import (
    AsyncSessionLocal,
    SyncSessionLocal,
    async_engine,
    sync_engine,
    get_async_session,
    get_sync_session,
    async_session_context,
    init_db,
    close_db,
)

__all__ = [
    # Base
    "Base",
    "metadata",
    "utc_now",
    # Models
    "User",
    "OAuthToken",
    "GitHubInstallation",
    "Repository",
    "PullRequest",
    "Review",
    "ReviewComment",
    "WebhookEvent",
    # Session
    "AsyncSessionLocal",
    "SyncSessionLocal",
    "async_engine",
    "sync_engine",
    "get_async_session",
    "get_sync_session",
    "async_session_context",
    "init_db",
    "close_db",
]