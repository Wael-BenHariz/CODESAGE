"""four-role vocabulary on users.role

Data migration to the four-role model
(docs/PLAN_ROLES_SETTINGS_STAGED.md §2, Step 1):

- ``SUPER_ADMIN`` -> ``PLATFORM_ADMIN``
- ``GUEST``       -> ``NONE`` (internal read-only sentinel)
- ``DEVELOPER``   -> unchanged;
- ``ORG_ADMIN`` / ``REVIEWER`` / ``NONE`` / ``PLATFORM_ADMIN`` pass through
  (they cannot exist yet — born with the new vocabulary in this release).

Also flips the column default to fail-closed ``NONE`` (a row inserted without
an explicit role is read-only) and refreshes the comment. App code always
inserts an explicit role (JIT provisioning derives it from the JWT), so the
default change is safe under a rolling deploy.

Reversible: ``downgrade`` restores the legacy strings, default and comment.
(Pre-existing ``ORG_ADMIN``/``REVIEWER`` rows — possible only if the new code
already ran — fall back to ``DEVELOPER``, the least-privileged legacy role;
``PLATFORM_ADMIN``/``NONE`` map back exactly.)

Revision ID: 012
Revises: 011
Create Date: 2026-10-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'PLATFORM_ADMIN' WHERE role = 'SUPER_ADMIN'")
    op.execute("UPDATE users SET role = 'NONE' WHERE role = 'GUEST'")

    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(32),
        server_default=sa.text("'NONE'"),
        comment="Realm role: PLATFORM_ADMIN | ORG_ADMIN | REVIEWER | DEVELOPER | NONE",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(32),
        server_default=sa.text("'DEVELOPER'"),
        comment="Realm role: SUPER_ADMIN | DEVELOPER | GUEST",
    )

    # Reverse the mapping. New-vocabulary roles that cannot exist pre-release
    # fall back to the least-privileged legacy role (DEVELOPER).
    op.execute("UPDATE users SET role = 'SUPER_ADMIN' WHERE role = 'PLATFORM_ADMIN'")
    op.execute("UPDATE users SET role = 'GUEST' WHERE role = 'NONE'")
    op.execute(
        "UPDATE users SET role = 'DEVELOPER' " "WHERE role IN ('ORG_ADMIN', 'REVIEWER')"
    )
