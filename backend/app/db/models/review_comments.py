"""Review comment model for inline code review comments."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.pull_requests import PullRequest
    from app.db.models.reviews import Review


class ReviewComment(Base):
    """Inline code review comment.

    Attributes:
        review_id: Reference to the parent review
        pull_request_id: Reference to the pull request (denormalized for queries)
        github_comment_id: GitHub comment ID (if posted to GitHub)
        file_path: Path to the file being commented on
        line_number: Line number in the file (optional for file-level comments)
        body: Comment text content
        severity: Comment severity (info, warning, error, suggestion)
        category: Category of the issue (bug, security, style, etc.)
        resolved: Whether the comment has been resolved
        resolved_at: When the comment was resolved
    """

    __tablename__ = "review_comments"
    __table_args__ = (
        # Index for review lookups
        # Index for file path queries
        # Index for GitHub comment sync
        {"comment": "Inline review comments with severity and category"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # Review reference
    review_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the parent review",
    )

    # Pull request reference (denormalized for faster queries)
    pull_request_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the pull request",
    )

    # GitHub Comment Reference
    github_comment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="GitHub comment ID if posted to GitHub",
    )

    # Comment Location
    file_path: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        index=True,
        comment="Path to the file being commented on",
    )

    line_number: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Line number in the file",
    )

    # Comment Content
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Comment text content",
    )

    # Comment Classification
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="info",
        index=True,
        comment="Severity: info, warning, error, suggestion",
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="general",
        index=True,
        comment="Category: bug, security, performance, style, etc.",
    )

    # Resolution Status
    resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the comment has been resolved",
    )

    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the comment was resolved",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    review: Mapped["Review"] = relationship(
        "Review",
        back_populates="comments",
    )

    pull_request: Mapped["PullRequest"] = relationship(
        "PullRequest",
        back_populates="review_comments",
    )

    def __repr__(self) -> str:
        return f"<ReviewComment(id={self.id}, file_path={self.file_path}, severity={self.severity})>"

    @property
    def is_resolved(self) -> bool:
        """Check if comment is resolved."""
        return self.resolved

    @property
    def is_posted_to_github(self) -> bool:
        """Check if comment has been posted to GitHub."""
        return self.github_comment_id is not None