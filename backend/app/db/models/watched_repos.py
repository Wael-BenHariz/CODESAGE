"""Watched repository model for GitHub App repository selection."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.users import User


class WatchedRepo(Base):
    """Repositories a user has enabled for code reviews."""

    __tablename__ = "watched_repos"
    __table_args__ = (
        UniqueConstraint("user_id", "repo_id", name="uq_watched_repos_user_repo"),
        {"comment": "GitHub repositories selected for review processing"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the user",
    )

    repo_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        comment="GitHub repository ID",
    )

    repo_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Repository full name (owner/repo)",
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether review processing is enabled",
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="watched_repos",
    )

    def __repr__(self) -> str:
        return f"<WatchedRepo(id={self.id}, repo_name={self.repo_name}, enabled={self.enabled})>"
