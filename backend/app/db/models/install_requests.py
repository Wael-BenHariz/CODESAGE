"""Install request model for RBAC."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.users import User
    from app.db.models.workspaces import Workspace


class InstallRequest(Base):
    """Install request model for tracking requests to install GitHub App in workspaces.

    Attributes:
        id: UUID primary key
        workspace_id: Foreign key to workspace
        requested_by: Foreign key to the user who requested the installation
        status: Status of the request (PENDING, APPROVED, REJECTED)
        resolved_by: Foreign key to the user who resolved the request (optional)
        resolved_at: Timestamp when the request was resolved (optional)
    """

    __tablename__ = "install_requests"

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

    requested_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the user who requested the installation",
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
        back_populates="install_requests",
    )

    requested_by_user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[requested_by],
        back_populates="install_requests_made",
    )

    resolved_by_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[resolved_by],
        back_populates="install_requests_resolved",
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_install_requests_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<InstallRequest(id={self.id}, workspace_id={self.workspace_id}, requested_by={self.requested_by}, status={self.status})>"
