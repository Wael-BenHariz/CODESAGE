"""review_comments source-finding enrichment (Step 7b)

Step 7b of docs/PLAN_ROLES_SETTINGS_STAGED.md:

The specialist LLM schema (``AgentComment``) never echoes source-finding
metadata, so the worker now stamps it onto each new comment by matching it
back to the normalized finding it refines. All columns are nullable —
comments written before this migration simply keep NULL and the review
panel degrades gracefully (no tool/rule badges, no snippet).

- ``tool`` / ``rule_id`` — provenance of the matched finding
- ``cwe`` — CWE ids of the matched finding (mirrors scan_findings.cwe)
- ``line_start`` / ``line_end`` — the finding's line range (may differ from
  the comment's own ``line_number``, which stays the anchor)
- ``snippet`` — source excerpt of the matched finding
- ``also_detected_by`` — other tools that found the same defect

Types mirror ``scan_findings`` (migration 010/011) so the two stay
comparable.

Revision ID: 015
Revises: 014
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_comments",
        sa.Column("tool", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "review_comments",
        sa.Column("rule_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "review_comments",
        sa.Column("line_start", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_comments",
        sa.Column("line_end", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_comments",
        sa.Column("snippet", sa.Text(), nullable=True),
    )
    op.add_column(
        "review_comments",
        sa.Column("cwe", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "review_comments",
        sa.Column("also_detected_by", postgresql.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_comments", "also_detected_by")
    op.drop_column("review_comments", "cwe")
    op.drop_column("review_comments", "snippet")
    op.drop_column("review_comments", "line_end")
    op.drop_column("review_comments", "line_start")
    op.drop_column("review_comments", "rule_id")
    op.drop_column("review_comments", "tool")
