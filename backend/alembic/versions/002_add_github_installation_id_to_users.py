"""add github_installation_id to users

Revision ID: 002
Revises: 001
Create Date: 2026-06-08 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("github_installation_id", sa.BigInteger(), nullable=True))
    op.create_index("idx_users_github_installation_id", "users", ["github_installation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_users_github_installation_id", table_name="users")
    op.drop_column("users", "github_installation_id")
