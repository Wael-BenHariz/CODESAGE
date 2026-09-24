"""add review result columns (overall_severity, github_review_id, suggestion)

Revision ID: 006
Revises: 005
Create Date: 2026-09-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Review: overall severity verdict + GitHub review ID (posted summary).
    op.add_column(
        "reviews",
        sa.Column(
            "overall_severity",
            sa.String(20),
            nullable=True,
            comment="Overall review severity: info, warning, error",
        ),
    )
    op.add_column(
        "reviews",
        sa.Column(
            "github_review_id",
            sa.BigInteger(),
            nullable=True,
            comment="GitHub pull request review ID",
        ),
    )
    op.create_index(
        "ix_reviews_github_review_id",
        "reviews",
        ["github_review_id"],
        unique=False,
    )

    # ReviewComment: optional inline suggestion text.
    op.add_column(
        "review_comments",
        sa.Column(
            "suggestion",
            sa.Text(),
            nullable=True,
            comment="Optional suggested fix for the comment",
        ),
    )


def downgrade() -> None:
    op.drop_column("review_comments", "suggestion")
    op.drop_index("ix_reviews_github_review_id", table_name="reviews")
    op.drop_column("reviews", "github_review_id")
    op.drop_column("reviews", "overall_severity")
