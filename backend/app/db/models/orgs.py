"""Organization, membership and organization settings models (Step 3).

One ``orgs`` row per GitHub App installation account, seeded from
``github_installations`` (plan Q1). The review authorization chain stays
joins-only — review → pull_request → repository → github_installation →
org (via ``orgs.installation_id``); no ``org_id`` columns are added to
reviews or repositories this release.
"""

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.users import User


class Org(Base):
    """GitHub account organization (one per App installation).

    Attributes:
        name: ``github_installations.account_login`` (no unique constraint —
            a reinstall may issue a new installation id; the org is re-linked,
            never duplicated).
        account_type: 'User' or 'Organization' (copied from the installation).
        installation_id: nullable UNIQUE FK to
            ``github_installations.installation_id`` (the numeric GitHub id,
            not the row PK) with ON DELETE SET NULL — an uninstall deletes
            the installation row but never wipes the org.

    Reinstall flow: uninstall nulls the link, reinstall re-links the same
    ``(name, account_type)`` org to the new installation id.
    """

    __tablename__ = "orgs"
    __table_args__ = (
        UniqueConstraint("installation_id", name="uq_orgs_installation_id"),
        {"comment": "Organizations seeded from GitHub App installations"},
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="GitHub account login (= github_installations.account_login)",
    )

    account_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="User",
        comment="'User' or 'Organization'",
    )

    # Nullable: uninstall (installation row deleted) nulls this via the FK's
    # ON DELETE SET NULL — the org survives without an install.
    installation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "github_installations.installation_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        unique=True,
        index=True,
        comment="GitHub App installation id (NULL when uninstalled)",
    )

    # Relationships
    members: Mapped[list["OrgMember"]] = relationship(
        "OrgMember",
        back_populates="org",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    settings: Mapped["OrgSetting | None"] = relationship(
        "OrgSetting",
        back_populates="org",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Org(id={self.id}, name={self.name}, "
            f"installation_id={self.installation_id})>"
        )


class OrgMember(Base):
    """Org membership: a user's role *within* one organization.

    Roles are restricted to the org-scoped vocabulary — ``DEVELOPER``,
    ``REVIEWER``, ``ORG_ADMIN``. ``PLATFORM_ADMIN`` is a global Keycloak
    role and is never stored here; ``NONE`` is a derivation-only sentinel
    and is never stored here either (plan Q4).

    UNIQUE (org_id, user_id): one row per member; re-seeding never
    downgrades an existing row (insert ... ON CONFLICT DO NOTHING).
    """

    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_members_org_id_user_id"),
        CheckConstraint(
            "role IN ('DEVELOPER', 'REVIEWER', 'ORG_ADMIN')",
            name="role_check",
        ),
        {"comment": "Org-scoped membership and role"},
    )

    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the organization",
    )

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the user",
    )

    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Org role: DEVELOPER | REVIEWER | ORG_ADMIN (never PLATFORM_ADMIN/NONE)",
    )

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="org_memberships")

    def __repr__(self) -> str:
        return (
            f"<OrgMember(org_id={self.org_id}, user_id={self.user_id}, "
            f"role={self.role})>"
        )


class OrgSetting(Base):
    """Per-org settings overrides — one row per org.

    Every column is nullable: NULL = "use the platform default, else the
    config/code default" (``resolve_org_settings`` only applies an org
    override when the column is non-NULL).
    """

    __tablename__ = "org_settings"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_org_settings_org_id"),
        {"comment": "Per-organization settings overrides (NULL = platform default)"},
    )

    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="One settings row per organization",
    )

    diff_char_cap: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Override: diff chars the LLM sees (ceiling-clamped on read)",
    )

    max_findings_per_agent: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Override: findings rendered into each specialist prompt",
    )

    max_concurrent_reviews: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Override: worker review concurrency",
    )

    enabled_agents: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Override: specialist domains to run ([] = summary only)",
    )

    sonarqube_enabled: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment="Override: run SonarQube in the scan stage",
    )

    semgrep_enabled: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment="Override: run Semgrep in the scan stage",
    )

    review_triggers: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Override: triggers that start reviews (pull_request, manual)",
    )

    min_severity_to_post: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="Override: lowest severity posted in auto mode",
    )

    posting_mode: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="Override: auto (post now) | staged (post after review)",
    )

    ai_model: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Override: LLM model for this org's reviews (NULL = system default)",
    )

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="settings")

    def __repr__(self) -> str:
        return f"<OrgSetting(org_id={self.org_id})>"


class PlatformSetting(Base):
    """Platform-wide defaults and ceilings — exactly one row.

    Nullable default columns fall back to the config/code defaults; the
    ceiling columns are seeded with the initial values from the plan table
    (never raisable above ``HARD_CAPS`` in code). The single-row invariant
    is enforced by a partial unique index on ``(true)`` created in the
    migration.
    """

    __tablename__ = "platform_settings"
    __table_args__ = (
        {"comment": "Platform settings: per-field defaults and ceilings"},
    )

    ceiling_diff_char_cap: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Ceiling for org diff_char_cap overrides (<= hard cap 100000)",
    )

    ceiling_max_findings_per_agent: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Ceiling for org max_findings_per_agent overrides (<= hard cap 100)",
    )

    ceiling_max_concurrent_reviews: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Ceiling for org max_concurrent_reviews overrides (<= hard cap 50)",
    )

    # Per-field platform DEFAULTS (NULL = config/code default wins).
    diff_char_cap: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Platform default diff cap (NULL = LLM_DIFF_CHAR_CAP config)",
    )

    max_findings_per_agent: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Platform default findings per agent (NULL = 15)",
    )

    max_concurrent_reviews: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Platform default concurrency (NULL = BULLMQ_CONCURRENCY config)",
    )

    enabled_agents: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Platform default specialist list (NULL = AGENT_DOMAINS)",
    )

    sonarqube_enabled: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment="Platform default SonarQube switch (NULL = true)",
    )

    semgrep_enabled: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment="Platform default Semgrep switch (NULL = SEMGREP_ENABLED config)",
    )

    review_triggers: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Platform default triggers (NULL = pull_request+manual)",
    )

    min_severity_to_post: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="Platform default post threshold (NULL = info)",
    )

    posting_mode: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="Platform default posting mode (NULL = auto)",
    )

    ai_model: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Platform default LLM model (NULL = system default)",
    )

    # created_at / updated_at are inherited from Base (as in Repository).
