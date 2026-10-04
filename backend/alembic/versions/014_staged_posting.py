"""staged posting: review posting columns + comment dismissal

Step 6 of docs/PLAN_ROLES_SETTINGS_STAGED.md:

- ``reviews.posting_mode`` (NOT NULL, server default ``auto``) — the org's
  effective posting mode at run time; existing rows default to ``auto``
  so every historical review behaves exactly as before.
- ``reviews.posted_at`` — when the summary actually reached GitHub
  (staged reviews and never-posted reviews stay NULL).
- ``reviews.edited_summary`` — human-edited staged summary; wins over
  ``summary`` when set (Q3 body base).
- ``review_comments.dismissed`` (NOT NULL, default false) plus
  ``dismissed_by``/``dismissed_at`` — dismissal state consumed by the
  staged Findings section (dismissed findings are excluded).

``reviews.github_review_id`` already exists (migration 006) — not re-added.

Revision ID: 014
Revises: 013
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Review: staged-posting columns.
    op.add_column(
        "reviews",
        sa.Column(
            "posting_mode",
            sa.String(length=16),
            nullable=False,
            server_default="auto",
            comment="Org posting mode at run time: auto | staged",
        ),
    )
    op.add_column(
        "reviews",
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the summary was posted to GitHub (NULL = never)",
        ),
    )
    op.add_column(
        "reviews",
        sa.Column(
            "edited_summary",
            sa.Text(),
            nullable=True,
            comment="Human-edited staged summary (wins over summary when set)",
        ),
    )

    # ReviewComment: dismissal state for the staged Findings section.
    op.add_column(
        "review_comments",
        sa.Column(
            "dismissed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Excluded from the staged Findings section when true",
        ),
    )
    op.add_column(
        "review_comments",
        sa.Column(
            "dismissed_by",
            sa.UUID(),
            nullable=True,
            comment="User who dismissed the comment",
        ),
    )
    op.create_foreign_key(
        "fk_review_comments_dismissed_by_users",
        "review_comments",
        "users",
        ["dismissed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "review_comments",
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the comment was dismissed",
        ),
    )


def downgrade() -> None:
    op.drop_column("review_comments", "dismissed_at")
    op.drop_constraint(
        "fk_review_comments_dismissed_by_users",
        "review_comments",
        type_="foreignkey",
    )
    op.drop_column("review_comments", "dismissed_by")
    op.drop_column("review_comments", "dismissed")
    op.drop_column("reviews", "edited_summary")
    op.drop_column("reviews", "posted_at")
    op.drop_column("reviews", "posting_mode")
