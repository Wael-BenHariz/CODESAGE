"""Repo-scoped org grants (repo-scoped invitations, migration 019).

One row per ``(user, org, repository)`` granted by an *accepted*
invitation: the org-level role still lives in ``org_members`` (never
downgraded), this table is the per-repository refinement the inviter
chose (single role for the whole selection, DEVELOPER | REVIEWER).

``github_collaborator`` records whether the best-effort "add the invitee
as a GitHub collaborator" pass succeeded — it makes the pass
idempotent (a retry only re-runs rows where it is false) and lets the
UI show a warning when the GitHub App lacked the permission.
"""

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.orgs import Org
    from app.db.models.repositories import Repository
    from app.db.models.users import User


class OrgMemberRepo(Base):
    """One repository granted to one org member (accepted invitation).

    Row identity: the inherited ``id`` PK, with a UNIQUE
    ``(user_id, org_id, repo_id)`` — the accept flow upserts on exactly
    those three columns, so re-accepting a later invitation for the same
    repo updates the row (role refresh + collaborator re-sync) instead of
    duplicating it. (``Base`` owns ``id``; marking the three columns as
    primary keys too would silently merge them into one composite PK
    that no ``ON CONFLICT`` target could match.)
    """

    __tablename__ = "org_member_repos"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "org_id",
            "repo_id",
            name="uq_org_member_repos_user_org_repo",
        ),
        CheckConstraint(
            "role IN ('DEVELOPER', 'REVIEWER')",
            name="repo_grant_role",
        ),
        {"comment": "Repo-scoped grants written when an invitation is accepted"},
    )

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="User granted the repository",
    )

    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        comment="Org the grant belongs to",
    )

    repo_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        comment="repositories.id row (full_name resolved from it)",
    )

    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Granted role: DEVELOPER | REVIEWER (CHECK)",
    )

    github_collaborator: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="GitHub App added the user as a collaborator (retry marker)",
    )

    github_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Why the collaborator add failed (NULL = succeeded)",
    )

    # Relationships (lazy — the routes query explicitly)
    user: Mapped["User"] = relationship("User", lazy="selectin")
    org: Mapped["Org"] = relationship("Org", lazy="selectin")
    repository: Mapped["Repository"] = relationship("Repository", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<OrgMemberRepo(user_id={self.user_id}, org_id={self.org_id}, "
            f"repo_id={self.repo_id}, role={self.role})>"
        )
