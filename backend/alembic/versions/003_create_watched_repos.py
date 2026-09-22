"""create watched_repos table

Revision ID: 003
Revises: 002
Create Date: 2026-06-08 18:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watched_repos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("repo_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_name", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "repo_id", name="uq_watched_repos_user_repo"),
        comment="GitHub repositories selected for review processing",
    )
    op.create_index("idx_watched_repos_user_id", "watched_repos", ["user_id"], unique=False)
    op.create_index("idx_watched_repos_repo_id", "watched_repos", ["repo_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_watched_repos_repo_id", table_name="watched_repos")
    op.drop_index("idx_watched_repos_user_id", table_name="watched_repos")
    op.drop_table("watched_repos")
