"""keycloak identity + role on users

Keycloak becomes the identity/token authority:
- users.keycloak_id — Keycloak subject (sub), the new identity key
- users.role — realm role synced from the JWT on every request
- users.github_id — relaxed to nullable (password-only Keycloak users have
  no GitHub identity; GitHub-brokered users keep it from the IdP mapper)

Revision ID: 008
Revises: 007
Create Date: 2026-09-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "keycloak_id",
            sa.String(64),
            nullable=True,
            comment="Keycloak subject (sub) claim",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(32),
            nullable=False,
            server_default="DEVELOPER",
            comment="Realm role: SUPER_ADMIN | DEVELOPER | GUEST",
        ),
    )
    op.create_index("ix_users_keycloak_id", "users", ["keycloak_id"], unique=True)

    # GitHub identity becomes optional (Keycloak-only users).
    op.alter_column(
        "users",
        "github_id",
        existing_type=sa.BigInteger(),
        nullable=True,
        comment="GitHub user ID",
    )


def downgrade() -> None:
    # Non-NULL github_id cannot be guaranteed on downgrade — refuse rather
    # than silently delete Keycloak-only rows.
    op.drop_index("ix_users_keycloak_id", table_name="users")
    op.drop_column("users", "role")
    op.drop_column("users", "keycloak_id")
    op.alter_column(
        "users",
        "github_id",
        existing_type=sa.BigInteger(),
        nullable=False,
        comment="GitHub user ID",
    )
