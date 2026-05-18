"""Pull request model."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.repositories import Repository
    from app.db.models.reviews import Review
    from app.db.models.review_comments import ReviewComment


class PullRequest(Base):
    """Pull request model for code review tracking.

    Attributes:
        repository_id: Reference to the repository
        github_pr_id: GitHub pull request ID
        number: PR number within the repository
        title: PR title
        body: PR description body
        state: PR state (open, closed, merged)
        author_login: GitHub username of the PR author
        author_avatar_url: Avatar URL of the PR author
        base_branch: Target branch name
        head_branch: Source branch name
        base_sha: SHA of the base commit
        head_sha: SHA of the head commit
        additions: Number of lines added
        deletions: Number of lines deleted
        changed_files: Number of files changed
    """

    __tablename__ = "pull_requests"
    __table_args__ = (
        # Unique constraint for github_pr_id per repository
        {"comment": "Pull requests being tracked for code review"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # Repository reference
    repository_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the repository",
    )

    # GitHub Identity
    github_pr_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="GitHub pull request ID",
    )

    number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="PR number within the repository",
    )

    # PR Content
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Pull request title",
    )

    body: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Pull request description body",
    )

    # PR State
    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        index=True,
        comment="PR state: open, closed, merged",
    )

    # Author Information
    author_login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="GitHub username of PR author",
    )

    author_avatar_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
        comment="Avatar URL of PR author",
    )

    # Branch Information
    base_branch: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Target branch name",
    )

    head_branch: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Source branch name",
    )

    base_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="SHA of the base commit",
    )

    head_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="SHA of the head commit",
    )

    # Change Statistics
    additions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of lines added",
    )

    deletions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of lines deleted",
    )

    changed_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of files changed",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(
        "Repository",
        back_populates="pull_requests",
    )

    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="pull_request",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    review_comments: Mapped[list["ReviewComment"]] = relationship(
        "ReviewComment",
        back_populates="pull_request",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<PullRequest(id={self.id}, number={self.number}, state={self.state})>"

    @property
    def is_open(self) -> bool:
        """Check if PR is open."""
        return self.state == "open"

    @property
    def is_merged(self) -> bool:
        """Check if PR is merged."""
        return self.state == "merged"