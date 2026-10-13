"""workspace RBAC schema drift: id server defaults + owner FK (from 020).

Migration 020 created the five workspace tables without the
``gen_random_uuid()`` server default that ``Base.id`` declares, and omitted
the ``workspaces.owner_user_id`` foreign key the model defines. Tests build
the schema via ``create_all`` (model), so the drift stayed invisible until a
fresh alembic-built DB served a real first login: the JIT
``ensure_personal_workspace`` INSERT omitted ``id`` and died on NOT NULL
(``null value in column "id" of relation "workspaces"`` -> 500).

Revision ID: 022
Revises: 021
Create Date: 2026-10-09

"""

import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

from alembic import op

# The five tables 020 created without Base.id's server default.
_ID_DEFAULT_TABLES = (
    "workspaces",
    "workspace_members",
    "dismissal_requests",
    "install_requests",
    "notifications",
)


def upgrade() -> None:
    for table in _ID_DEFAULT_TABLES:
        op.alter_column(
            table,
            "id",
            server_default=sa.text("gen_random_uuid()"),
        )
    op.create_foreign_key(
        "fk_workspaces_owner_user_id_users",
        "workspaces",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_workspaces_owner_user_id_users",
        "workspaces",
        type_="foreignkey",
    )
    for table in reversed(_ID_DEFAULT_TABLES):
        op.alter_column(table, "id", server_default=None)
