"""repo_tenants - one enabled repo = one tenant/namespace (repo-tenant-service)

The table lives in the shared `codesage` database but is OWNED by the
repo-tenant-service microservice (Spring Data JPA, ddl-auto: none): this
migration creates the physical schema, the service only reads/writes rows.

Revision ID: 009
Revises: 008
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repo_tenants",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repo_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(512), nullable=False),
        sa.Column("owner_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("namespace_name", sa.String(63), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provisioning_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", name="uq_repo_tenants_repo_id"),
        sa.UniqueConstraint("namespace_name", name="uq_repo_tenants_namespace_name"),
        comment="One enabled repo = one tenant/namespace (repo-tenant-service)",
    )
    op.create_index("ix_repo_tenants_status", "repo_tenants", ["status"])
    op.create_index("ix_repo_tenants_updated_at", "repo_tenants", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_repo_tenants_updated_at", table_name="repo_tenants")
    op.drop_index("ix_repo_tenants_status", table_name="repo_tenants")
    op.drop_table("repo_tenants")
