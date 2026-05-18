"""OAuth token model for encrypted token storage."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.users import User


class OAuthToken(Base):
    """Encrypted OAuth tokens for GitHub API access.

    Attributes:
        user_id: Reference to the user who owns these tokens
        access_token: Encrypted GitHub access token
        refresh_token: Encrypted GitHub refresh token (for token refresh)
        expires_at: When the access token expires
    """

    __tablename__ = "oauth_tokens"
    __table_args__ = (
        # Index for user lookups (common query)
        {"comment": "Encrypted OAuth tokens for GitHub API access"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # Ownership
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the user",
    )

    # Encrypted token storage
    # Note: In production, these should be encrypted at the application level
    # or using pgcrypto extension. The TEXT type stores encrypted blobs.
    access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Encrypted GitHub access token",
    )

    refresh_token: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Encrypted GitHub refresh token for token refresh",
    )

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Token expiration timestamp",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="oauth_tokens",
    )

    def __repr__(self) -> str:
        return f"<OAuthToken(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at