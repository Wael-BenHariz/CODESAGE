"""add scan_findings.also_detected_by (cross-tool dedup annotations)

Column added after 010: ``merge_findings`` records which OTHER tools
reported the same defect; the review API round-trips that to
``NormalizedFinding.also_detected_by``.

Revision ID: 011
Revises: 010
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scan_findings",
        sa.Column(
            "also_detected_by",
            sa.ARRAY(sa.String()),
            nullable=True,
            comment="Other tools that reported this defect (primary tool excluded)",
        ),
    )


def downgrade() -> None:
    op.drop_column("scan_findings", "also_detected_by")
