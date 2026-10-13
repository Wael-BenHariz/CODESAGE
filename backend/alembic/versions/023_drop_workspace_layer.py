"""Remove the workspace layer — simple RBAC (orgs + invitations only).

Owner decision (docs/rbac-decisions.md #12): the workspace flow (v0.5.0,
migrations 020-022) is dropped in favour of a simpler model:

* global role from the Keycloak token (GitHub signup -> ORG_ADMIN),
* one ``org_members`` role per org — the invitation's role **wins** inside
  that org,
* installing the GitHub App auto-creates the org with the installer as
  ORG_ADMIN (org provisioning, least-privilege rule).

So this migration drops the five workspace tables (``workspaces``,
``workspace_members``, ``dismissal_requests``, ``install_requests``,
``notifications`` — the governance features built on them are dropped per
the same decision) and the ``workspace_id`` columns 020 added to the six
core tables. Org tables (``orgs``, ``org_members``, ``org_invitations``,
``org_member_repos``) are untouched.

The data itself does not need preserving (workspace_members mirrored
org_members; orgs keep their own rows) — no backfill here.

Revision ID: 023
Revises: 022
Create Date: 2026-10-10

"""

import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None

from alembic import op

# Columns 020 added, with their index names — dropped column-wise first so
# the FKs into ``workspaces`` are gone before the table itself falls.
_COLUMN_DROPS: tuple[tuple[str, str], ...] = (
    ("orgs", "ix_orgs_workspace_id"),
    ("watched_repos", "ix_watched_repos_workspace_id"),
    ("pull_requests", "ix_pull_requests_workspace_id"),
    ("reviews", "ix_reviews_workspace_id"),
    ("github_installations", "ix_github_installations_workspace_id"),
    ("repositories", "ix_repositories_workspace_id"),
)

# Children before parents: the request/notification tables reference both
# workspaces and users/review_comments.
_TABLE_DROPS = (
    "notifications",
    "install_requests",
    "dismissal_requests",
    "workspace_members",
    "workspaces",
)


def upgrade() -> None:
    for table, index in _COLUMN_DROPS:
        op.drop_index(index, table_name=table)
        # Dropping the column also drops its FK constraint into workspaces.
        op.drop_column(table, "workspace_id")

    for table in _TABLE_DROPS:
        op.drop_table(table)


def downgrade() -> None:
    """Structural re-creation of the 020-022 schema (no data backfill).

    020's data backfill is intentionally not repeated: fresh rows bind via
    the runtime provisioning paths.
    """
    op.create_table(
        "workspaces",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("github_account_login", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "type", "owner_user_id", name="uq_workspaces_type_owner_user_id"
        ),
        sa.CheckConstraint("type IN ('PERSONAL', 'ORG')", name="ck_workspaces_type"),
    )

    op.create_table(
        "workspace_members",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name="uq_workspace_members_workspace_id_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "role IN ('ORG_ADMIN', 'REVIEWER', 'DEVELOPER', 'NONE')",
            name="ck_workspace_members_role",
        ),
    )

    op.create_table(
        "dismissal_requests",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("review_comment_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="PENDING"
        ),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["review_comment_id"], ["review_comments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_dismissal_requests_status",
        ),
    )

    op.create_table(
        "install_requests",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="PENDING"
        ),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_install_requests_status",
        ),
    )

    op.create_table(
        "notifications",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("related_id", sa.UUID(), nullable=True),
        sa.Column("related_type", sa.String(length=50), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="SET NULL"
        ),
    )

    # Re-add workspace_id columns (FK + index as 020 created them).
    column_specs: tuple[tuple[str, str, str], ...] = (
        ("repositories", "CASCADE", "ix_repositories_workspace_id"),
        ("github_installations", "CASCADE", "ix_github_installations_workspace_id"),
        ("reviews", "CASCADE", "ix_reviews_workspace_id"),
        ("pull_requests", "CASCADE", "ix_pull_requests_workspace_id"),
        ("watched_repos", "CASCADE", "ix_watched_repos_workspace_id"),
        ("orgs", "SET NULL", "ix_orgs_workspace_id"),
    )
    for table, ondelete, index in column_specs:
        op.add_column(table, sa.Column("workspace_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            None, table, "workspaces", ["workspace_id"], ["id"], ondelete=ondelete
        )
        op.create_index(index, table, ["workspace_id"])
