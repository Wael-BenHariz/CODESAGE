"""add updated_at to review_comments

Revision ID: 005
Revises: 004
Create Date: 2026-09-22 21:55:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Same drift as webhook_events (004): Base declares updated_at for every
    # model, but 001 omitted it here — loading PullRequest.review_comments
    # (e.g. during webhook PR creation or Repository delete) crashed with
    # UndefinedColumnError.
    op.add_column(
        "review_comments",
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
        CREATE TRIGGER update_review_comments_updated_at
        BEFORE UPDATE ON review_comments
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column()
    """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS update_review_comments_updated_at ON review_comments")
    op.drop_column("review_comments", "updated_at")
