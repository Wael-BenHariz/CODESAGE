"""review_finding_validations (Step 9)

Step 9 of docs/PLAN_ROLES_SETTINGS_STAGED.md:

Reviewers (effective role >= REVIEWER) can judge each finding of a
review. One row per (comment, reviewer):

- ``verdict`` — confirmed | false_positive | needs_investigation (CHECK)
- ``severity_override`` — optional reviewer-assigned severity, NULL keeps
  the original (CHECK against the four severities when present)
- ``note`` — plain-text justification, stored as-is (the frontend renders
  it through Angular interpolation only)

``UNIQUE (comment_id, reviewer_id)`` is what makes the endpoint an
upsert: a changed mind replaces the verdict instead of piling up rows
(``ON CONFLICT ... DO UPDATE`` in the route).

Revision ID: 016
Revises: 015
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_finding_validations",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("comment_id", sa.UUID(), nullable=False),
        sa.Column("reviewer_id", sa.UUID(), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("severity_override", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # ``ck`` naming convention = ck_%(table_name)s_%(constraint_name)s
        # (app/db/base.py): the explicit name feeds the template, so pass
        # the SUFFIX only.
        sa.CheckConstraint(
            "verdict IN ('confirmed', 'false_positive', 'needs_investigation')",
            name="verdict",
        ),
        sa.CheckConstraint(
            "severity_override IS NULL OR "
            "severity_override IN ('info', 'warning', 'error', 'suggestion')",
            name="severity_override",
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"], ["review_comments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comment_id",
            "reviewer_id",
            name="uq_review_finding_validations_comment_reviewer",
        ),
        comment="Reviewer verdicts on individual review findings (plan Step 9)",
    )


def downgrade() -> None:
    op.drop_table("review_finding_validations")
