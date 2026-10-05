"""Reviewer verdicts on individual review findings (plan Step 9)."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.review_comments import ReviewComment
    from app.db.models.users import User


class ReviewFindingValidation(Base):
    """One reviewer's verdict for one review finding (comment).

    ``UNIQUE (comment_id, reviewer_id)``: a changed mind replaces the
    verdict — the endpoint upserts with ``ON CONFLICT ... DO UPDATE``
    (plan Step 9). Verdict/severity enums are mirrored as CHECK
    constraints in migration 016.

    Attributes:
        comment_id: The finding this verdict judges
        reviewer_id: The org member who judged it (effective role >= REVIEWER)
        verdict: confirmed | false_positive | needs_investigation
        severity_override: Reviewer-assigned severity, NULL keeps the
            finding's original severity
        note: Free-text justification — plain text, stored as-is
            (the frontend renders it via Angular interpolation only)
    """

    __tablename__ = "review_finding_validations"
    __table_args__ = (
        UniqueConstraint(
            "comment_id",
            "reviewer_id",
            name="uq_review_finding_validations_comment_reviewer",
        ),
        {"comment": "Reviewer verdicts on individual review findings (plan Step 9)"},
    )

    comment_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_comments.id", ondelete="CASCADE"),
        nullable=False,
        comment="The finding this verdict judges",
    )

    reviewer_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Org member who submitted the verdict",
    )

    verdict: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="confirmed | false_positive | needs_investigation",
    )

    severity_override: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="Reviewer-assigned severity; NULL keeps the original",
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Plain-text justification, stored as-is",
    )

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
    comment: Mapped["ReviewComment"] = relationship(
        "ReviewComment",
        back_populates="validations",
    )

    # selectin: `reviewer_login` must resolve without an async lazy-load
    # while GET /reviews/{id} serializes the comment's validations.
    reviewer: Mapped["User"] = relationship(
        "User",
        lazy="selectin",
    )

    @property
    def reviewer_login(self) -> str:
        """Login of the verdict's author (eager-loaded — see relationship)."""
        return self.reviewer.login if self.reviewer is not None else "unknown"

    def __repr__(self) -> str:
        return (
            f"<ReviewFindingValidation(id={self.id}, verdict={self.verdict}, "
            f"reviewer_id={self.reviewer_id})>"
        )
