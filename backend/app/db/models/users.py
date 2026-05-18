"""User model for GitHub OAuth users."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.oauth_tokens import OAuthToken
    from app.db.models.reviews import Review


class User(Base):
    """GitHub OAuth user account.

    Attributes:
        github_id: GitHub user ID (unique)
        login: GitHub username (unique)
        email: User's email address
        name: Display name (optional)
        avatar_url: GitHub avatar URL
    """

    __tablename__ = "users"
    __table_args__ = (
        # Unique constraint for github_id
        # Unique constraint for login (username)
        {"comment": "GitHub OAuth users with authentication tokens"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # GitHub Identity
    github_id: Mapped[int] = mapped_column(
        nullable=False,
        unique=True,
        index=True,
        comment="GitHub user ID",
    )

    login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="GitHub username",
    )

    email: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="User email address",
    )

    name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="User display name",
    )

    avatar_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
        comment="GitHub avatar URL",
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
    oauth_tokens: Mapped[list["OAuthToken"]] = relationship(
        "OAuthToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, login={self.login})>"

    @property
    def is_active(self) -> bool:
        """Check if user is active (has valid token)."""
        if not self.oauth_tokens:
            return False
        return any(not token.is_expired for token in self.oauth_tokens)