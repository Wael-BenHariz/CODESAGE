"""Webhook event model for GitHub webhook delivery tracking."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.repositories import Repository


class WebhookEvent(Base):
    """GitHub webhook delivery event.

    Stores all incoming webhook events for audit, replay, and debugging.
    Events are stored before processing and marked as processed after.

    Attributes:
        repository_id: Reference to the repository
        event_type: Type of GitHub event (pull_request, push, etc.)
        delivery_id: Unique delivery ID from GitHub
        action: Action that triggered the event
        payload: Full JSON payload from GitHub
        processed: Whether the event has been processed
    """

    __tablename__ = "webhook_events"
    __table_args__ = (
        # Unique constraint for delivery_id (idempotency)
        # Index for event type filtering
        # Index for processing queue
        {"comment": "Audit trail of all GitHub webhook deliveries"},
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

    # Event Identification
    event_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Type of GitHub event (e.g., 'pull_request', 'push')",
    )

    delivery_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="GitHub delivery ID for idempotency",
    )

    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Action that triggered the event (e.g., 'opened', 'synchronize')",
    )

    # Payload Storage
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Full JSON payload from GitHub",
    )

    # Processing State
    processed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="Whether the event has been processed",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(
        "Repository",
        back_populates="webhook_events",
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent(id={self.id}, event_type={self.event_type}, action={self.action}, processed={self.processed})>"

    @property
    def is_processed(self) -> bool:
        """Check if event has been processed."""
        return self.processed

    @property
    def is_pending(self) -> bool:
        """Check if event is pending processing."""
        return not self.processed