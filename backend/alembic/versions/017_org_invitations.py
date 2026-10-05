"""org_invitations (Step 11)

Step 11 of docs/PLAN_ROLES_SETTINGS_STAGED.md:

- ``email`` — the invitee (raw token never stored, only its SHA-256 hash)
- ``role`` — CHECK against the two *invitable* roles only: ORG_ADMIN and
  PLATFORM_ADMIN can never be granted by an invitation
- ``token_hash`` — SHA-256 hex of ``secrets.token_urlsafe(32)``; UNIQUE so
  the public preview/accept endpoints look up by hash and a token can
  never collide or be enumerated from the DB
- ``status`` — CHECK pending | accepted | revoked | expired, default
  pending; single-use via a conditional UPDATE in the accept transaction
- ``expires_at`` — now() + 7 days (computed by the app at creation)

Reversible: ``downgrade`` drops the table only.

Revision ID: 017
Revises: 016
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_invitations",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # ``ck`` naming convention = ck_%(table_name)s_%(constraint_name)s —
        # the explicit name feeds the template, so pass the suffix only.
        sa.CheckConstraint(
            "role IN ('DEVELOPER', 'REVIEWER')",
            name="invitable_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="lifecycle",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_org_invitations_token_hash"),
        comment="Org invitations — raw token never stored (SHA-256 hash only)",
    )


def downgrade() -> None:
    op.drop_table("org_invitations")
