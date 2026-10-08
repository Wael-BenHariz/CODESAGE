"""Workspace models for RBAC."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, String, Text, func, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


if TYPE_CHECKING:
    from app.db.models.users import User


class Workspace(Base):
    """Workspace model for RBAC.
    
    Attributes:
        id: UUID primary key
        type: Either 'PERSONAL' or 'ORG'
        name: Human-readable name for the workspace
        owner_user_id: For PERSONAL workspaces, the user who owns it; for ORG workspaces, nullable
        github_account_login: For ORG workspaces linked to GitHub, the GitHub account login
    """
    
    __tablename__ = "workspaces"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Workspace type: PERSONAL or ORG",
    )
    
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable workspace name",
    )
    
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="For PERSONAL workspaces: owning user; for ORG workspaces: nullable",
    )
    
    github_account_login: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="For ORG workspaces: GitHub account login",
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
    owner_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[owner_user_id],
        back_populates="owned_workspaces",
    )
    
    members: Mapped[list["WorkspaceMember"]] = relationship(
        "WorkspaceMember",
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="select",
    )
    
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository",
        back_populates="workspace",
        lazy="select",
    )
    
    github_installations: Mapped[list["GitHubInstallation"]] = relationship(
        "GitHubInstallation",
        back_populates="workspace",
        lazy="select",
    )
    
    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="workspace",
        lazy="select",
    )
    
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        "PullRequest",
        back_populates="workspace",
        lazy="select",
    )
    
    watched_repos: Mapped[list["WatchedRepo"]] = relationship(
        "WatchedRepo",
        back_populates="workspace",
        lazy="select",
    )
    
    orgs: Mapped[list["Org"]] = relationship(
        "Org",
        back_populates="workspace",
        lazy="select",
    )
    
    dismissal_requests: Mapped[list["DismissalRequest"]] = relationship(
        "DismissalRequest",
        back_populates="workspace",
        lazy="select",
    )
    
    install_requests: Mapped[list["InstallRequest"]] = relationship(
        "InstallRequest",
        back_populates="workspace",
        lazy="select",
    )
    
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="workspace",
        lazy="select",
    )
    
    # Constraints
    __table_args__ = (
        CheckConstraint("type IN ('PERSONAL', 'ORG')", name='ck_workspaces_type'),
    )
    
    def __repr__(self) -> str:
        return f"<Workspace(id={self.id}, type={self.type}, name={self.name})>"


class WorkspaceMember(Base):
    """Workspace membership model linking users to workspaces with roles.
    
    Attributes:
        id: UUID primary key
        workspace_id: Foreign key to workspace
        user_id: Foreign key to user
        role: Role within the workspace (ORG_ADMIN, REVIEWER, DEVELOPER, NONE)
    """
    
    __tablename__ = "workspace_members"
    
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
    
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the user",
    )
    
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Role within workspace: ORG_ADMIN, REVIEWER, DEVELOPER, NONE",
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
        back_populates="members",
    )
    
    user: Mapped["User"] = relationship(
        "User",
        back_populates="workspace_memberships",
    )
    
    # Constraints
    __table_args__ = (
        CheckConstraint("role IN ('ORG_ADMIN', 'REVIEWER', 'DEVELOPER', 'NONE')", name='ck_workspace_members_role'),
    )
    
    def __repr__(self) -> str:
        return f"<WorkspaceMember(id={self.id}, workspace_id={self.workspace_id}, user_id={self.user_id}, role={self.role})>"