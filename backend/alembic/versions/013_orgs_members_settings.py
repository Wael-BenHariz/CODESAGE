"""orgs, org_members, org_settings, platform_settings + seeding

Step 3 of docs/PLAN_ROLES_SETTINGS_STAGED.md (Q1 decision):

- ``orgs`` — one row per GitHub App installation account, seeded from
  ``github_installations`` (name = account_login, account_type copied,
  installation_id nullable UNIQUE FK with ON DELETE SET NULL so an
  uninstall never wipes the org). Reinstall re-links by
  ``(name, account_type)``; a new install inserts.
- ``org_members`` — least-privilege seeding from ``users`` whose
  ``github_installation_id`` matches the installation: exactly one linked
  user → ORG_ADMIN, two or more → all DEVELOPER, zero → no members.
  Never promote everyone. ``ON CONFLICT (org_id, user_id) DO NOTHING`` —
  re-running never downgrades (or duplicates) an existing row.
- ``org_settings`` — one row per org, every column NULL (= use platform /
  config default).
- ``platform_settings`` — exactly one row (partial unique index on
  ``(true)``). Ceiling columns seeded with the initial values (100000 /
  50 / 10); default columns left NULL so the config/code defaults stay
  authoritative (``LLM_DIFF_CHAR_CAP``, ``BULLMQ_CONCURRENCY``,
  ``SEMGREP_ENABLED``, ``AGENT_DOMAINS``, …) — "nullable = fall back to
  config/code default" per the plan.

Seeding is idempotent (safe re-run) and mirrors
``app/services/org_provisioning.py``, which the webhook/link hooks and
``scripts/org_seed_report.py`` use at runtime.

Reversible: ``downgrade`` drops only the four new tables (order respects
the FKs). Nothing existing is modified.

Revision ID: 013
Revises: 012
Create Date: 2026-10-04 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- orgs ---------------------------------------------------------------
    op.create_table(
        "orgs",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "account_type", sa.String(length=50), nullable=False, server_default="User"
        ),
        sa.Column("installation_id", sa.BigInteger(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["github_installations.installation_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id", name="uq_orgs_installation_id"),
        comment="Organizations seeded from GitHub App installations",
    )
    op.create_index("ix_orgs_name", "orgs", ["name"])
    op.create_index("ix_orgs_installation_id", "orgs", ["installation_id"])

    # --- org_members --------------------------------------------------------
    op.create_table(
        "org_members",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
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
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_members_org_id_user_id"),
        # Vocabulary enforcement (plan §2): PLATFORM_ADMIN is global-only and
        # NONE is a sentinel — neither may ever be stored here. The name is
        # the *suffix*: the metadata convention renders it as
        # ck_<table>_role_check (a full name would be double-prefixed).
        sa.CheckConstraint(
            "role IN ('DEVELOPER', 'REVIEWER', 'ORG_ADMIN')",
            name="role_check",
        ),
        comment="Org-scoped membership and role",
    )
    op.create_index("ix_org_members_org_id", "org_members", ["org_id"])
    op.create_index("ix_org_members_user_id", "org_members", ["user_id"])

    # --- org_settings -------------------------------------------------------
    op.create_table(
        "org_settings",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("diff_char_cap", sa.Integer(), nullable=True),
        sa.Column("max_findings_per_agent", sa.Integer(), nullable=True),
        sa.Column("max_concurrent_reviews", sa.Integer(), nullable=True),
        sa.Column(
            "enabled_agents", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("sonarqube_enabled", sa.Boolean(), nullable=True),
        sa.Column("semgrep_enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "review_triggers", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("min_severity_to_post", sa.String(length=16), nullable=True),
        sa.Column("posting_mode", sa.String(length=16), nullable=True),
        sa.Column("ai_model", sa.String(length=128), nullable=True),
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
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_org_settings_org_id"),
        comment="Per-organization settings overrides (NULL = platform default)",
    )
    op.create_index("ix_org_settings_org_id", "org_settings", ["org_id"])

    # --- platform_settings --------------------------------------------------
    op.create_table(
        "platform_settings",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("ceiling_diff_char_cap", sa.Integer(), nullable=True),
        sa.Column("ceiling_max_findings_per_agent", sa.Integer(), nullable=True),
        sa.Column("ceiling_max_concurrent_reviews", sa.Integer(), nullable=True),
        sa.Column("diff_char_cap", sa.Integer(), nullable=True),
        sa.Column("max_findings_per_agent", sa.Integer(), nullable=True),
        sa.Column("max_concurrent_reviews", sa.Integer(), nullable=True),
        sa.Column(
            "enabled_agents", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("sonarqube_enabled", sa.Boolean(), nullable=True),
        sa.Column("semgrep_enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "review_triggers", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("min_severity_to_post", sa.String(length=16), nullable=True),
        sa.Column("posting_mode", sa.String(length=16), nullable=True),
        sa.Column("ai_model", sa.String(length=128), nullable=True),
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
        comment="Platform settings: per-field defaults and ceilings",
    )
    # Single-row invariant: at most one row in the table.
    op.create_index(
        "uq_platform_settings_single",
        "platform_settings",
        [sa.text("(true)")],
        unique=True,
    )

    # --- seeding ------------------------------------------------------------
    # 1) Re-link first: an org orphaned by an uninstall (installation_id
    #    NULL) is re-adopted when the same (name, account_type) installs
    #    again under a NEW installation id — never duplicated.
    op.execute("""
        UPDATE orgs o
        SET installation_id = i.installation_id, updated_at = NOW()
        FROM github_installations i
        WHERE o.installation_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM orgs o2 WHERE o2.installation_id = i.installation_id
          )
          AND o.name = i.account_login
          AND o.account_type = i.account_type
        """)

    # 2) One org per installation that has no org yet.
    op.execute("""
        INSERT INTO orgs (name, account_type, installation_id)
        SELECT i.account_login, i.account_type, i.installation_id
        FROM github_installations i
        WHERE NOT EXISTS (
            SELECT 1 FROM orgs o WHERE o.installation_id = i.installation_id
        )
        """)

    # 3) Least-privilege members: users linked to the installation.
    #    Exactly one linked user -> ORG_ADMIN (the single holder is the
    #    linker); two or more -> all DEVELOPER; zero -> no rows.
    #    DO NOTHING: re-running never downgrades an existing row.
    op.execute("""
        INSERT INTO org_members (id, org_id, user_id, role)
        SELECT gen_random_uuid(), o.id, u.id,
               CASE WHEN linked.cnt = 1 THEN 'ORG_ADMIN' ELSE 'DEVELOPER' END
        FROM orgs o
        JOIN (
            SELECT github_installation_id, COUNT(*) AS cnt
            FROM users
            WHERE github_installation_id IS NOT NULL
            GROUP BY github_installation_id
        ) linked ON linked.github_installation_id = o.installation_id
        JOIN users u ON u.github_installation_id = o.installation_id
        ON CONFLICT (org_id, user_id) DO NOTHING
        """)

    # 4) Single platform row: ceilings only (initial values). Default
    #    columns stay NULL -> config/code defaults remain authoritative.
    op.execute("""
        INSERT INTO platform_settings (
            id, created_at, updated_at,
            ceiling_diff_char_cap,
            ceiling_max_findings_per_agent,
            ceiling_max_concurrent_reviews
        ) VALUES (
            gen_random_uuid(), NOW(), NOW(), 100000, 50, 10
        )
        """)


def downgrade() -> None:
    # Drops only the tables this revision added (data included — the
    # seeding is fully reproducible by re-upgrading).
    op.drop_index("uq_platform_settings_single", table_name="platform_settings")
    op.drop_table("platform_settings")
    op.drop_index("ix_org_settings_org_id", table_name="org_settings")
    op.drop_table("org_settings")
    op.drop_index("ix_org_members_user_id", table_name="org_members")
    op.drop_index("ix_org_members_org_id", table_name="org_members")
    op.drop_table("org_members")
    op.drop_index("ix_orgs_installation_id", table_name="orgs")
    op.drop_index("ix_orgs_name", table_name="orgs")
    op.drop_table("orgs")
