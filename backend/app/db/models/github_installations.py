"""GitHub App installation model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.repositories import Repository
    from app.db.models.workspaces import Workspace


class GitHubInstallation(Base):
    """GitHub App installation for organization/user.

    Represents a GitHub App installation, linking the app to a user
    or organization account. Stores permissions and configuration.

    Attributes:
        app_id: GitHub App ID
        installation_id: Unique GitHub installation ID
        account_id: GitHub account (user/org) ID
        account_login: GitHub account username
        account_type: 'user' or 'organization'
        permissions: JSON object with permission grants
    """

    __tablename__ = "github_installations"
    __table_args__ = (
        # Unique constraint for installation_id (each installation is unique)
        {"comment": "GitHub App installations linking app to accounts"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # GitHub App Identity
    app_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="GitHub App ID",
    )

    installation_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
        comment="Unique GitHub installation ID",
    )

    # Account Information
    account_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="GitHub account (user/org) ID",
    )

    account_login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="GitHub account username",
    )

    account_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="'user' or 'organization'",
    )

    # Permissions granted to the installation
    permissions: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="JSON object with GitHub permission grants",
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

    # Workspace association
    workspace_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Reference to the workspace",
    )

    # Relationships
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository",
        back_populates="installation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Workspace relationship
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
        back_populates="github_installations",
    )

    def __repr__(self) -> str:
        return f"<GitHubInstallation(id={self.id}, installation_id={self.installation_id}, account={self.account_login})>"
