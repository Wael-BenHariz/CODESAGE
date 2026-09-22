"""add updated_at to webhook_events

Revision ID: 004
Revises: 003
Create Date: 2026-09-22 21:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Base declares updated_at for every model, but 001 omitted it for
    # webhook_events only — every event INSERT (and any Repository delete that
    # loads the webhook_events relationship) crashed with UndefinedColumnError.
    op.add_column(
        "webhook_events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    # Same auto-update trigger as the other tables (function created in 001).
    op.execute(
        """
        CREATE TRIGGER update_webhook_events_updated_at
        BEFORE UPDATE ON webhook_events
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column()
    """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS update_webhook_events_updated_at ON webhook_events")
    op.drop_column("webhook_events", "updated_at")
