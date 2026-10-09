"""Dismissal request model for RBAC."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.review_comments import ReviewComment
    from app.db.models.users import User
    from app.db.models.workspaces import Workspace


class DismissalRequest(Base):
    """Dismissal request model for tracking requests to dismiss review comments.
    
    Attributes:
        id: UUID primary key
        workspace_id: Foreign key to workspace
        review_comment_id: Foreign key to the review comment being requested for dismissal
        requested_by: Foreign key to the user who requested the dismissal
        reason: Reason for the dismissal request
        status: Status of the request (PENDING, APPROVED, REJECTED)
        resolved_by: Foreign key to the user who resolved the request (optional)
        resolved_at: Timestamp when the request was resolved (optional)
    """
    
    __tablename__ = "dismissal_requests"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the workspace",
    )
    
    review_comment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_comments.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the review comment being requested for dismissal",
    )
    
    requested_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the user who requested the dismissal",
    )
    
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Reason for the dismissal request",
    )
    
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="PENDING",
        comment="Status of the request: PENDING, APPROVED, REJECTED",
    )
    
    resolved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Reference to the user who resolved the request",
    )
    
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the request was resolved",
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
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
        back_populates="dismissal_requests",
    )
    
    # One-way on purpose: ReviewComment has no reverse collection — every
    # query goes through DismissalRequest.review_comment_id, so a second
    # relationship on review_comments.py would be dead weight.
    review_comment: Mapped["ReviewComment"] = relationship(
        "ReviewComment",
    )
    
    requested_by_user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[requested_by],
        back_populates="dismissal_requests_made",
    )
    
    resolved_by_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[resolved_by],
        back_populates="dismissal_requests_resolved",
    )
    
    # Constraints
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name='ck_dismissal_requests_status'),
    )
    
    def __repr__(self) -> str:
        return f"<DismissalRequest(id={self.id}, workspace_id={self.workspace_id}, review_comment_id={self.review_comment_id}, status={self.status})>"