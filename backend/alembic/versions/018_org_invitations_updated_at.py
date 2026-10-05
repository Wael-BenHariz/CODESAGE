"""org_invitations.updated_at (Step 13 hotfix)

Migration 017 created ``org_invitations`` without the ``updated_at``
column that ``Base`` (``app/db/base.py``) declares on every model.
Unit tests build the schema with ``create_all`` straight from the
models, so the drift never surfaced locally — it only appeared against
a migrated database during the v0.3.0 cluster release (Step 13), where
the public invitation preview endpoint failed with
``column org_invitations.updated_at does not exist``.

Additive and reversible: adds the column with the exact shape every
other table received in 013 (``DateTime(timezone=True)``, ``NOW()``
server default, NOT NULL).

Revision ID: 018
Revises: 017
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "org_invitations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("org_invitations", "updated_at")
