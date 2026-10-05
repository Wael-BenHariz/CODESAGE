"""Org provisioning: keep ``orgs`` / ``org_members`` in sync with GitHub.

Single implementation of the plan's least-privilege seeding rule (Q1),
shared by:

- migration 013 (the SQL there mirrors this module — same rule, same
  order: re-link reinstall, then insert, then members),
- the installation **webhook** hook (``_handle_installation_event``),
- the **link** hooks: signed-state install callback and the
  ``_adopt_github_installation`` self-heal in ``app.security.dependencies``,
- ``scripts/org_seed_report.py`` (dry-run report + ``--apply`` heal).

Least-privilege rule — members are the users whose
``users.github_installation_id`` equals the installation:

- exactly **one** linked user → ``ORG_ADMIN`` (the schema's single holder
  is the linker: the callback writes the link directly and adoption can
  only match one row per ``github_id``);
- **two or more** → all ``DEVELOPER`` ("cannot tell" branch — never
  promote everyone);
- **zero** → no members.

Existing member rows are never downgraded (or upgraded) by re-seeding:
missing rows are inserted with ``ON CONFLICT DO NOTHING``.

Contract: the provisioning functions **flush, never commit** — the caller
owns the transaction (webhook, callback, script).
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GitHubInstallation, Org, OrgMember, User

logger = logging.getLogger(__name__)

# Org-scoped vocabulary — PLATFORM_ADMIN is global, NONE is a sentinel;
# neither is ever stored in org_members.
ROLE_ORG_ADMIN = "ORG_ADMIN"
ROLE_DEVELOPER = "DEVELOPER"
ORG_MEMBER_ROLES = (ROLE_DEVELOPER, "REVIEWER", ROLE_ORG_ADMIN)


def least_privilege_role(linked_user_count: int) -> str | None:
    """Role for a *new* member row given how many users link the install.

    0 → None (no members at all), 1 → ORG_ADMIN, ≥2 → DEVELOPER.
    Pure function so the migration SQL, the runtime hooks, the dry-run
    script and the tests all exercise the identical rule.
    """
    if linked_user_count <= 0:
        return None
    if linked_user_count == 1:
        return ROLE_ORG_ADMIN
    return ROLE_DEVELOPER


async def provision_installation_org(
    db: AsyncSession,
    installation: GitHubInstallation,
) -> Org:
    """Upsert the org for one installation, then seed missing members.

    Lookup order (plan Q1): by ``installation_id`` (steady state) →
    re-link an existing org by ``(name, account_type)`` whose link was
    nulled by an uninstall (reinstall under a new id — never duplicate)
    → insert a new org.

    Flushes only; the caller commits.
    """
    result = await db.execute(
        select(Org).where(Org.installation_id == installation.installation_id)
    )
    org = result.scalar_one_or_none()

    if org is None:
        # Reinstall: adopt the org the uninstall orphaned (link = NULL).
        result = await db.execute(
            select(Org)
            .where(
                Org.name == installation.account_login,
                Org.account_type == installation.account_type,
                Org.installation_id.is_(None),
            )
            .order_by(Org.created_at.asc())
            .limit(1)
        )
        org = result.scalar_one_or_none()
        if org is not None:
            org.installation_id = installation.installation_id
            logger.info(
                "org_relinked org_id=%s name=%r installation_id=%s",
                org.id,
                org.name,
                installation.installation_id,
            )
        else:
            org = Org(
                name=installation.account_login,
                account_type=installation.account_type,
                installation_id=installation.installation_id,
            )
            db.add(org)
            await db.flush()
            logger.info(
                "org_created org_id=%s name=%r installation_id=%s",
                org.id,
                org.name,
                installation.installation_id,
            )
    else:
        # Installation row is authoritative (account rename / type change).
        org.name = installation.account_login
        org.account_type = installation.account_type

    inserted = await sync_org_members(db, org)
    if inserted:
        logger.info("org_members_seeded org_id=%s inserted=%s", org.id, inserted)
    return org


async def sync_org_members(db: AsyncSession, org: Org) -> int:
    """Insert membership rows missing for users linked to the org's install.

    The role comes from the least-privilege rule over the TOTAL linked
    users (a second user linking an installation where the first already
    holds ORG_ADMIN gets DEVELOPER — the existing row is never touched).
    No-op when the org has no installation link (uninstalled).

    Flushes only; the caller commits. Returns the number of rows inserted.
    """
    if org.installation_id is None:
        return 0

    linked_ids = select(User.id).where(
        User.github_installation_id == org.installation_id
    )
    total = (
        await db.execute(select(func.count()).select_from(linked_ids.subquery()))
    ).scalar_one()
    role = least_privilege_role(total)
    if role is None:
        return 0

    # Missing rows only (existing rows are never downgraded/ upgraded).
    missing = await db.execute(
        select(User.id, User.login)
        .where(
            User.github_installation_id == org.installation_id,
            User.id.not_in(select(OrgMember.user_id).where(OrgMember.org_id == org.id)),
        )
        .order_by(User.created_at.asc())
    )
    rows = [
        {"org_id": org.id, "user_id": user_id, "role": role}
        for user_id, _login in missing.all()
    ]
    if not rows:
        return 0

    inserted = await db.execute(
        pg_insert(OrgMember)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["org_id", "user_id"])
    )
    await db.flush()
    # execute() is typed as Result, but an INSERT returns a CursorResult.
    return int(getattr(inserted, "rowcount", 0) or 0)


async def provision_for_installation_id(
    db: AsyncSession,
    installation_id: int,
) -> Org | None:
    """Provision by numeric GitHub installation id; None when unknown.

    Used by the install callback, whose signed state carries only the id —
    when the ``github_installations`` row does not exist yet (webhook not
    delivered), this is a no-op and the webhook hook covers it later.
    """
    result = await db.execute(
        select(GitHubInstallation).where(
            GitHubInstallation.installation_id == installation_id
        )
    )
    installation = result.scalar_one_or_none()
    if installation is None:
        return None
    return await provision_installation_org(db, installation)


async def provision_for_user_link(db: AsyncSession, user: User) -> None:
    """Link hook: ``user.github_installation_id`` was just written.

    Ensures the org exists and the user's membership row is seeded. No-op
    when the installation row is missing (webhook hook covers it) or the
    user has no link.
    """
    if user.github_installation_id is None:
        return
    await provision_for_installation_id(db, int(user.github_installation_id))


# --- dry-run report (scripts/org_seed_report.py) ----------------------------


@dataclass
class PlannedOrgReport:
    """What provisioning *would* create for one installation."""

    name: str
    account_type: str
    installation_id: int
    org_exists: bool
    members: list[dict] = field(default_factory=list)  # {"login", "role"} planned
    missing_members: list[str] = field(default_factory=list)  # logins w/o a row

    @property
    def has_org_admin(self) -> bool:
        return any(m["role"] == ROLE_ORG_ADMIN for m in self.members)


@dataclass
class SeedReport:
    """Dry-run summary: planned vs current state of orgs and members."""

    planned: list[PlannedOrgReport]
    current: list[dict]  # {"name", "installation_id", "members", "has_org_admin"}
    orgs_table_exists: bool


async def seed_report(db: AsyncSession) -> SeedReport:
    """Read-only summary of what provisioning would create vs what exists.

    Works before migration 013 (``orgs`` table missing → ``current`` is
    empty, ``orgs_table_exists`` False) so the rollout gate can show the
    plan before the cluster migration runs.
    """
    installations = (
        await db.execute(
            select(
                GitHubInstallation.installation_id,
                GitHubInstallation.account_login,
                GitHubInstallation.account_type,
            ).order_by(GitHubInstallation.account_login.asc())
        )
    ).all()

    # Linked users per installation (login order = deterministic report).
    linked: dict[int, list[str]] = {}
    for installation_id, login in (
        await db.execute(
            select(User.github_installation_id, User.login)
            .where(User.github_installation_id.is_not(None))
            .order_by(User.created_at.asc())
        )
    ).all():
        if installation_id is None:  # filtered above; keeps the type checker happy
            continue
        linked.setdefault(int(installation_id), []).append(login)

    # Existing orgs / members (tolerate "table doesn't exist" pre-013).
    orgs_exists = True
    try:
        org_rows = (
            await db.execute(
                select(Org.id, Org.name, Org.installation_id).order_by(Org.name.asc())
            )
        ).all()
        member_rows = (
            await db.execute(
                select(OrgMember.org_id, OrgMember.user_id, OrgMember.role)
            )
        ).all()
        user_logins = {
            str(uid): login
            for uid, login in (await db.execute(select(User.id, User.login))).all()
        }
    except Exception:  # noqa: BLE001 — pre-migration run: tables absent
        await db.rollback()
        org_rows, member_rows, user_logins = [], [], {}
        orgs_exists = False

    orgs_by_install = {row[2]: row for row in org_rows if row[2] is not None}
    members_by_org: dict[str, list[str]] = {}
    roles_by_org: dict[str, list[str]] = {}
    for org_id, user_id, role in member_rows:
        key = str(org_id)
        members_by_org.setdefault(key, []).append(
            user_logins.get(str(user_id), str(user_id))
        )
        roles_by_org.setdefault(key, []).append(role)

    planned: list[PlannedOrgReport] = []
    for installation_id, login, account_type in installations:
        org_row = orgs_by_install.get(installation_id)
        linked_logins = linked.get(int(installation_id), [])
        role = least_privilege_role(len(linked_logins))
        entry = PlannedOrgReport(
            name=login,
            account_type=account_type,
            installation_id=installation_id,
            org_exists=org_row is not None,
        )
        if role is not None:
            entry.members = [{"login": lg, "role": role} for lg in linked_logins]
        if org_row is not None:
            existing_logins = set(members_by_org.get(str(org_row[0]), []))
            entry.missing_members = [
                lg for lg in linked_logins if lg not in existing_logins
            ]
        planned.append(entry)

    current: list[dict] = []
    if orgs_exists:
        for org_id, name, installation_id in org_rows:
            key = str(org_id)
            current.append(
                {
                    "name": name,
                    "installation_id": installation_id,
                    "members": members_by_org.get(key, []),
                    "has_org_admin": ROLE_ORG_ADMIN in roles_by_org.get(key, []),
                }
            )

    return SeedReport(planned=planned, current=current, orgs_table_exists=orgs_exists)
