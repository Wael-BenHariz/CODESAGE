"""install_requests.resolved_at — persist the approval/rejection timestamp.

The approve/reject handlers write ``resolved_at`` but 020 only created
``resolved_by``, so the timestamp was computed per-response and lost.

Revision ID: 021
Revises: 020
Create Date: 2026-10-09

"""

import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.add_column(
        "install_requests",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("install_requests", "resolved_at")
