"""Org invitation model (plan Step 11)."""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrgInvitation(Base):
    """One invitation to join an org (plan Step 11).

    The raw token exists only in the emailed link: the database stores
    its SHA-256 hash (UNIQUE) — the public preview/accept endpoints look
    up by hash, so no token can be enumerated from the DB and a leaked
    row never yields a usable link.

    ``role`` is constrained to the two *invitable* roles: ORG_ADMIN and
    PLATFORM_ADMIN can never be granted by an invitation. ``status`` is
    single-use — accept flips pending → accepted with a conditional
    UPDATE (rowcount 0 → 409, double-click safe).

    Attributes:
        org_id: Org being joined
        email: Invitee address as typed (trimmed); compared
            case-insensitively on accept (mismatch is allowed + warned)
        role: DEVELOPER | REVIEWER (CHECK in migration 017 + model)
        repository_ids: uuid[] of the repositories this invitation
            grants with ``role`` (empty = org-only, the pre-existing
            behaviour) — one role for the whole selection
        github_error: joined summary of the best-effort GitHub
            collaborator pass run at accept time (NULL = all good)
        token_hash: SHA-256 hex of ``secrets.token_urlsafe(32)``
        status: pending | accepted | revoked | expired
        expires_at: now() + 7 days, computed at creation
        invited_by: ORG_ADMIN who created the invitation
    """

    __tablename__ = "org_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_org_invitations_token_hash"),
        CheckConstraint("role IN ('DEVELOPER', 'REVIEWER')", name="invitable_role"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="lifecycle",
        ),
        {"comment": "Org invitations — raw token never stored (SHA-256 hash only)"},
    )

    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        comment="Org being joined",
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Invitee email address (trimmed, stored as typed)",
    )

    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Invitable role: DEVELOPER or REVIEWER (CHECK)",
    )

    repository_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default="{}",
        comment="repositories.id rows granted with `role` ([] = org-only)",
    )

    github_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Joined GitHub collaborator errors from accept (NULL = ok)",
    )

    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hex of the raw token — the raw token is never stored",
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="pending",
        comment="pending | accepted | revoked | expired (CHECK)",
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="now() + 7 days at creation time",
    )

    invited_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="ORG_ADMIN who created the invitation",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    @property
    def is_expired(self) -> bool:
        """True when the invitation passed its 7-day window."""
        return self.expires_at <= datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return (
            f"<OrgInvitation(id={self.id}, org_id={self.org_id}, "
            f"email={self.email!r}, status={self.status})>"
        )
