"""User model for GitHub OAuth users."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.oauth_tokens import OAuthToken
    from app.db.models.orgs import OrgMember
    from app.db.models.reviews import Review
    from app.db.models.watched_repos import WatchedRepo


class User(Base):
    """User account (identity owned by Keycloak).

    Attributes:
        keycloak_id: Keycloak subject (sub) — primary identity key.
        role: Realm role synced from the JWT on every authenticated request
            (PLATFORM_ADMIN | ORG_ADMIN | REVIEWER | DEVELOPER | NONE —
            legacy SUPER_ADMIN/GUEST claims map through the one-release
            compat map in ``app.security.roles``).
        github_id: GitHub user ID from the GitHub IdP broker (optional —
            password-only Keycloak users have none).
        login: GitHub username (unique)
        email: User's email address
        name: Display name (optional)
        avatar_url: GitHub avatar URL
    """

    __tablename__ = "users"
    __table_args__ = (
        # Unique constraint for github_id
        # Unique constraint for login (username)
        {"comment": "Keycloak users with GitHub identity"},
    )

    # Primary key (inherited from Base)
    # id: UUID (inherited)

    # Keycloak Identity
    keycloak_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
        comment="Keycloak subject (sub) claim",
    )

    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        # Fail-closed: a row inserted without an explicit role is read-only.
        server_default="NONE",
        comment="Realm role: PLATFORM_ADMIN | ORG_ADMIN | REVIEWER | DEVELOPER | NONE",
    )

    # GitHub Identity (from the GitHub IdP broker)
    github_id: Mapped[int | None] = mapped_column(
        nullable=True,
        unique=True,
        index=True,
        comment="GitHub user ID",
    )

    login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="GitHub username",
    )

    email: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="User email address",
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="User display name",
    )

    avatar_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="GitHub avatar URL",
    )

    github_installation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="GitHub App installation ID linked to the user",
    )

    # Per-user LLM settings — resolved by the worker at review job time.
    # llm_api_key stores the AES-Fernet encrypted value (never plaintext);
    # NULL anywhere = fall back to the system default Groq client.
    llm_provider: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="LLM provider: groq | openai | anthropic | gemini | ollama",
    )

    llm_model: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Per-user model override",
    )

    llm_api_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Fernet-encrypted LLM API key",
    )

    llm_base_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Custom endpoint base URL (Ollama / OpenAI-compatible)",
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
    oauth_tokens: Mapped[list["OAuthToken"]] = relationship(
        "OAuthToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    watched_repos: Mapped[list["WatchedRepo"]] = relationship(
        "WatchedRepo",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    org_memberships: Mapped[list["OrgMember"]] = relationship(
        "OrgMember",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, login={self.login})>"

    @property
    def is_active(self) -> bool:
        """Always true — activity checked via token queries."""
        return True
