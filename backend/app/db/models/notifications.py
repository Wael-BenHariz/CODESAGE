"""Notification model for RBAC."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.users import User
    from app.db.models.workspaces import Workspace


class Notification(Base):
    """Notification model for sending notifications to users.
    
    Attributes:
        id: UUID primary key
        user_id: Foreign key to the user receiving the notification
        workspace_id: Foreign key to the workspace (optional, for workspace-specific notifications)
        type: Type of notification (e.g., 'install_request', 'dismissal_request', etc.)
        title: Title of the notification
        message: Detailed message of the notification (optional)
        is_read: Whether the notification has been read
        related_id: ID of the related entity (optional)
        related_type: Type of the related entity (optional)
    """
    
    __tablename__ = "notifications"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the user receiving the notification",
    )
    
    workspace_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Reference to the workspace (for workspace-specific notifications)",
    )
    
    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of notification",
    )
    
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Title of the notification",
    )
    
    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Detailed message of the notification",
    )
    
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa.text("false"),
        comment="Whether the notification has been read",
    )
    
    related_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        comment="ID of the related entity",
    )
    
    related_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Type of the related entity",
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
        back_populates="notifications",
    )
    
    workspace: Mapped["Workspace | None"] = relationship(
        "Workspace",
        back_populates="notifications",
    )
    
    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, user_id={self.user_id}, type={self.type}, is_read={self.is_read})>"