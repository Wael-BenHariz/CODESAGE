"""org_invitation repo grants + org_member_repos (repo-scoped invites)

An ORG_ADMIN can now invite a teammate to one or more repositories with
a single role (DEVELOPER | REVIEWER — the two invitable roles, the same
vocabulary migration 017 already CHECKs on ``org_invitations.role``):

- ``org_invitations.repository_ids`` — uuid[] of the repositories the
  invitation grants (empty array = org-only invitation, the pre-existing
  behaviour). An array (not a join table) because there is exactly one
  role for the whole selection: one column, one value, no partial state.
  No FK is possible on an array element, so the ids are validated
  against the org's installation in the route (they are only read at
  accept time, where they are re-resolved and silently skipped if the
  repository row is gone).
- ``org_invitations.github_error`` — joined summary of the best-effort
  "add invitee as GitHub collaborator" pass run at accept time; NULL
  when everything succeeded (or there was nothing to grant).
- ``org_member_repos`` — the *effective* per-repo grant, written when the
  invitation is accepted: ``id`` PK (inherited from ``Base``) + UNIQUE
  ``(user_id, org_id, repo_id)`` — the accept upsert target — the granted
  role, ``github_collaborator`` (has the GitHub App successfully added
  the user? — idempotency/retry marker) and the per-repo error.

Only DEVELOPER/REVIEWER can ever be granted here (CHECK mirrors 017's
``invitable_role``).

Additive and reversible: ``downgrade`` drops both columns and the table.

Revision ID: 019
Revises: 018
Create Date: 2026-10-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "org_invitations",
        sa.Column(
            "repository_ids",
            postgresql.ARRAY(sa.UUID()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "org_invitations",
        sa.Column("github_error", sa.Text(), nullable=True),
    )

    op.create_table(
        "org_member_repos",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "github_collaborator",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("github_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "role IN ('DEVELOPER', 'REVIEWER')",
            name="repo_grant_role",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "org_id",
            "repo_id",
            name="uq_org_member_repos_user_org_repo",
        ),
        comment="Repo-scoped grants written when an invitation is accepted",
    )


def downgrade() -> None:
    op.drop_table("org_member_repos")
    op.drop_column("org_invitations", "github_error")
    op.drop_column("org_invitations", "repository_ids")
