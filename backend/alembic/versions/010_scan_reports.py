"""scan_reports + scan_findings - unified static analysis findings

Additive tables for the Semgrep integration: one report header per scan and
one row per normalized finding (typed columns for filtering by tool /
severity). Nothing existing is modified — old columns keep working.

Revision ID: 010
Revises: 009
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_reports",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("scan_id", sa.String(length=64), nullable=False),
        sa.Column(
            "tools_run",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tools_failed",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Unified static analysis scan reports (one row per scan)",
    )
    op.create_index("ix_scan_reports_review_id", "scan_reports", ["review_id"])
    op.create_index("ix_scan_reports_scan_id", "scan_reports", ["scan_id"])

    op.create_table(
        "scan_findings",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("fingerprint", sa.String(length=40), nullable=False),
        sa.Column("tool", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.String(length=255), server_default="", nullable=False),
        sa.Column("title", sa.String(length=512), server_default="", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column(
            "category",
            sa.String(length=32),
            server_default="best_practice",
            nullable=False,
        ),
        sa.Column(
            "file_path", sa.String(length=1024), server_default="", nullable=False
        ),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("cwe", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("owasp", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("reference_urls", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("fix_suggestion", sa.Text(), nullable=True),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["report_id"], ["scan_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Normalized findings from static analyzers",
    )
    op.create_index("ix_scan_findings_report_id", "scan_findings", ["report_id"])
    op.create_index("ix_scan_findings_fingerprint", "scan_findings", ["fingerprint"])
    op.create_index("ix_scan_findings_tool", "scan_findings", ["tool"])
    op.create_index("ix_scan_findings_severity", "scan_findings", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_scan_findings_severity", table_name="scan_findings")
    op.drop_index("ix_scan_findings_tool", table_name="scan_findings")
    op.drop_index("ix_scan_findings_fingerprint", table_name="scan_findings")
    op.drop_index("ix_scan_findings_report_id", table_name="scan_findings")
    op.drop_table("scan_findings")
    op.drop_index("ix_scan_reports_scan_id", table_name="scan_reports")
    op.drop_index("ix_scan_reports_review_id", table_name="scan_reports")
    op.drop_table("scan_reports")
