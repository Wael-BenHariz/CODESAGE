"""Repository model for GitHub repositories."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.github_installations import GitHubInstallation
    from app.db.models.pull_requests import PullRequest
    from app.db.models.webhook_events import WebhookEvent


class Repository(Base):
    """GitHub repository linked to a GitHub App installation.

    Attributes:
        installation_id: Reference to the GitHub App installation
        github_repo_id: GitHub repository ID
        name: Repository name (without owner)
        full_name: Full name (owner/repo format)
        private: Whether the repository is private
        default_branch: Default branch name (usually 'main' or 'master')
        webhook_id: GitHub webhook ID for this repository
        enabled: Whether CodeSage is enabled for this repository
    """

    __tablename__ = "repositories"
    __table_args__ = (
        # Unique constraint for github_repo_id per installation
        # Unique constraint for full_name
        {"comment": "GitHub repositories connected to CodeSage"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # Installation reference
    installation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("github_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the GitHub App installation",
    )

    # GitHub Identity
    github_repo_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="GitHub repository ID",
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Repository name (without owner)",
    )

    full_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True,
        index=True,
        comment="Full name in owner/repo format",
    )

    # Repository Properties
    private: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the repository is private",
    )

    default_branch: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="main",
        comment="Default branch name",
    )

    # Webhook Configuration
    webhook_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="GitHub webhook ID for this repository",
    )

    # Repository Status
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether CodeSage is enabled for this repository",
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
    installation: Mapped["GitHubInstallation"] = relationship(
        "GitHubInstallation",
        back_populates="repositories",
    )

    pull_requests: Mapped[list["PullRequest"]] = relationship(
        "PullRequest",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    webhook_events: Mapped[list["WebhookEvent"]] = relationship(
        "WebhookEvent",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Repository(id={self.id}, full_name={self.full_name})>"