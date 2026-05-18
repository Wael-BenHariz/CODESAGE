"""Review model for AI code review sessions."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.pull_requests import PullRequest
    from app.db.models.review_comments import ReviewComment
    from app.db.models.users import User


class Review(Base):
    """AI/Human code review for a pull request.

    Attributes:
        pull_request_id: Reference to the pull request
        user_id: Reference to the user who triggered the review (optional)
        status: Review status (pending, processing, completed, failed)
        error_message: Error message if review failed
        summary: Review summary text
        gemini_model: AI model used for the review
        tokens_used: Number of tokens consumed
        started_at: When the review started processing
        completed_at: When the review completed
    """

    __tablename__ = "reviews"
    __table_args__ = (
        # Index for pull request lookups
        # Index for status filtering
        {"comment": "AI and human reviews for pull requests"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # Pull Request reference
    pull_request_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the pull request",
    )

    # User who triggered the review
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who triggered the review",
    )

    # Review Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="Review status: pending, processing, completed, failed",
    )

    # Review Content
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if review failed",
    )

    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Review summary text",
    )

    # AI Model Information
    gemini_model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="AI model used for the review",
    )

    tokens_used: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of tokens consumed",
    )

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When the review started processing",
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the review completed",
    )

    # Timestamps (inherited from Base)
    # created_at: datetime
    # updated_at: datetime

    # Relationships
    pull_request: Mapped["PullRequest"] = relationship(
        "PullRequest",
        back_populates="reviews",
    )

    user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="reviews",
    )

    comments: Mapped[list["ReviewComment"]] = relationship(
        "ReviewComment",
        back_populates="review",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Review(id={self.id}, pull_request_id={self.pull_request_id}, status={self.status})>"

    @property
    def is_pending(self) -> bool:
        """Check if review is pending."""
        return self.status == "pending"

    @property
    def is_completed(self) -> bool:
        """Check if review is completed successfully."""
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        """Check if review failed."""
        return self.status == "failed"

    @property
    def processing_duration_seconds(self) -> Optional[float]:
        """Calculate processing duration in seconds."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None