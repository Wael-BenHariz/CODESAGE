"""Org provisioning: least-privilege seeding, re-install re-link, survival, hooks.

Covers the plan Q1 contract shared by migration 013 (same rule in SQL),
the webhook/link hooks and ``scripts/org_seed_report.py``:

- exactly one linked user → ORG_ADMIN; two or more → all DEVELOPER;
  zero → member-less org;
- idempotent re-runs, existing rows never downgraded;
- uninstall nulls the link (org + members survive), reinstall re-links
  the same (name, account_type) org — never duplicates it;
- ``org_members.role`` CHECK: PLATFORM_ADMIN/NONE can never be stored.
"""

import pytest
from conftest import make_keycloak_token
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.routes.auth import _create_installation_state_token
from app.api.routes.webhooks import _handle_installation_event
from app.config import settings
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    User,
)
from app.services.org_provisioning import (
    ROLE_ORG_ADMIN,
    least_privilege_role,
    provision_for_installation_id,
    provision_installation_org,
    seed_report,
    sync_org_members,
)

API = settings.API_V1_PREFIX

# == conftest user.github_id
ACCOUNT_ID = 111222333


def _auth(keycloak_id: str, roles: tuple[str, ...] = ("DEVELOPER",)) -> dict:
    return {
        "Authorization": f"Bearer {make_keycloak_token(sub=keycloak_id, roles=roles)}"
    }


async def _make_user(
    db, keycloak_id: str, *, github_installation_id=None, github_id=None
) -> User:
    row = User(
        keycloak_id=keycloak_id,
        login=keycloak_id,
        role="DEVELOPER",
        github_id=github_id,
        github_installation_id=github_installation_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _installation(
    installation_id: int,
    *,
    login: str = "acme",
    account_type: str = "Organization",
    account_id: int = 900_001,
) -> GitHubInstallation:
    return GitHubInstallation(
        app_id=1,
        installation_id=installation_id,
        account_id=account_id,
        account_login=login,
        account_type=account_type,
    )


async def _members(db, org: Org) -> list[OrgMember]:
    result = await db.execute(
        select(OrgMember)
        .where(OrgMember.org_id == org.id)
        .order_by(OrgMember.created_at)
    )
    return list(result.scalars().all())


async def _user_row(db, user: User) -> User:
    # populate_existing: expire_on_commit=False keeps the identity-map object
    # alive, so a plain re-SELECT would serve its stale attributes instead of
    # the row the app session just committed (cross-session writes).
    result = await db.execute(
        select(User).where(User.id == user.id).execution_options(populate_existing=True)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Pure rule
# ---------------------------------------------------------------------------


def test_least_privilege_role_rule():
    assert least_privilege_role(0) is None
    assert least_privilege_role(1) == ROLE_ORG_ADMIN
    assert least_privilege_role(2) == "DEVELOPER"
    assert least_privilege_role(10) == "DEVELOPER"


# ---------------------------------------------------------------------------
# Provisioning core
# ---------------------------------------------------------------------------


async def test_single_linked_user_becomes_org_admin(db):
    installation = _installation(555_001, login="solo-org")
    db.add(installation)
    user = await _make_user(db, "kc-solo", github_installation_id=555_001)
    # _make_user commits: installation + user land in the same transaction
    # (the org's FK needs the installation row to exist).
    await db.commit()

    org = await provision_installation_org(db, installation)
    await db.commit()

    assert org.name == "solo-org"
    assert org.installation_id == 555_001
    members = await _members(db, org)
    assert len(members) == 1
    assert members[0].user_id == user.id
    assert members[0].role == ROLE_ORG_ADMIN


async def test_two_linked_users_are_all_developers(db):
    installation = _installation(555_002, login="team-org")
    db.add(installation)
    await db.commit()
    await _make_user(db, "kc-a", github_installation_id=555_002)
    await _make_user(db, "kc-b", github_installation_id=555_002)

    org = await provision_installation_org(db, installation)
    await db.commit()

    members = await _members(db, org)
    assert len(members) == 2
    assert {m.role for m in members} == {"DEVELOPER"}


async def test_zero_linked_users_yields_member_less_org(db):
    installation = _installation(555_003, login="ghost-org")
    db.add(installation)
    await db.commit()

    org = await provision_installation_org(db, installation)
    await db.commit()

    assert org.name == "ghost-org"
    assert await _members(db, org) == []


async def test_provisioning_is_idempotent(db):
    installation = _installation(555_004, login="idem-org")
    db.add(installation)
    await db.commit()
    await _make_user(db, "kc-idem", github_installation_id=555_004)

    org_first = await provision_installation_org(db, installation)
    org_second = await provision_installation_org(db, installation)
    await db.commit()

    assert org_first.id == org_second.id
    orgs = (await db.execute(select(Org).where(Org.name == "idem-org"))).scalars().all()
    assert len(orgs) == 1
    assert len(await _members(db, org_first)) == 1


async def test_second_link_never_downgrades_first_org_admin(db):
    """Sole linker holds ORG_ADMIN; a later second user gets DEVELOPER."""
    installation = _installation(555_005, login="grow-org")
    db.add(installation)
    await db.commit()
    first = await _make_user(db, "kc-first", github_installation_id=555_005)

    org = await provision_installation_org(db, installation)
    await db.commit()
    assert (await _members(db, org))[0].role == ROLE_ORG_ADMIN

    await _make_user(db, "kc-second", github_installation_id=555_005)
    await provision_installation_org(db, installation)
    await db.commit()

    by_user = {m.user_id: m.role for m in await _members(db, org)}
    assert by_user[first.id] == ROLE_ORG_ADMIN  # never downgraded
    assert set(by_user.values()) == {ROLE_ORG_ADMIN, "DEVELOPER"}


async def test_uninstall_keeps_org_and_members(db):
    installation = _installation(555_006, login="survivor-org")
    db.add(installation)
    await db.commit()
    await _make_user(db, "kc-survivor", github_installation_id=555_006)
    org = await provision_installation_org(db, installation)
    await db.commit()

    # Uninstall deletes the installation row; FK ON DELETE SET NULL the link.
    await db.delete(installation)
    await db.commit()

    reloaded = (
        await db.execute(
            select(Org)
            .where(Org.id == org.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert reloaded.installation_id is None
    assert len(await _members(db, reloaded)) == 1  # membership survives

    # sync is a no-op while the org has no installation link.
    assert await sync_org_members(db, reloaded) == 0


async def test_reinstall_relinks_same_org_never_duplicates(db):
    installation = _installation(555_007, login="relink-org")
    db.add(installation)
    await db.commit()
    await _make_user(db, "kc-relink", github_installation_id=555_007)
    org_before = await provision_installation_org(db, installation)
    await db.commit()

    await db.delete(installation)
    await db.commit()

    # Reinstall under a NEW installation id, same (name, account_type).
    new_installation = _installation(555_008, login="relink-org")
    db.add(new_installation)
    await db.commit()

    org_after = await provision_for_installation_id(db, 555_008)
    await db.commit()

    assert org_after is not None
    assert org_after.id == org_before.id  # same row — re-linked, not duplicated
    assert org_after.installation_id == 555_008
    orgs = (
        (await db.execute(select(Org).where(Org.name == "relink-org"))).scalars().all()
    )
    assert len(orgs) == 1
    assert len(await _members(db, org_after)) == 1  # membership survived


async def test_provision_for_unknown_installation_is_none(db):
    assert await provision_for_installation_id(db, 999_999_999) is None


async def test_org_members_check_rejects_platform_admin_and_none(db):
    """CHECK: only DEVELOPER/REVIEWER/ORG_ADMIN are storable (§2)."""
    installation = _installation(555_009, login="check-org")
    db.add(installation)
    await db.commit()
    user = await _make_user(db, "kc-check")
    org = await provision_installation_org(db, installation)
    await db.commit()
    # 0 linked users -> member-less org, so only the invalid rows are tried.
    assert await _members(db, org) == []

    # Captured before the loop: rollback() expires every instance, and a
    # lazy re-read would raise MissingGreenlet in async context.
    org_id, user_id = org.id, user.id
    for bad_role in ("PLATFORM_ADMIN", "NONE"):
        db.add(OrgMember(org_id=org_id, user_id=user_id, role=bad_role))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


# ---------------------------------------------------------------------------
# Hooks: webhook / signed-state callback / JIT adoption
# ---------------------------------------------------------------------------


def _installation_created_payload(*, account_id: int = ACCOUNT_ID) -> dict:
    return {
        "action": "created",
        "installation": {
            "id": 987_654_321,
            "app_id": 1,
            "account": {"id": account_id, "login": "test-user", "type": "User"},
            "permissions": {"contents": "read"},
            "events": ["pull_request"],
        },
        "repositories": [],
    }


async def test_webhook_installation_created_provisions_org_and_member(db, user):
    result = await _handle_installation_event(
        _installation_created_payload(), "delivery-org-1", db
    )
    await db.commit()
    assert result["status"] == "success"

    row = await _user_row(db, user)
    assert row.github_installation_id == 987_654_321

    org = (await db.execute(select(Org).where(Org.name == "test-user"))).scalar_one()
    assert org.installation_id == 987_654_321
    members = await _members(db, org)
    assert len(members) == 1
    assert members[0].user_id == user.id
    assert members[0].role == ROLE_ORG_ADMIN  # sole linked user


async def test_install_callback_provisions_membership(client, db, user):
    db.add(
        _installation(
            987_654_321, login="test-user", account_type="User", account_id=ACCOUNT_ID
        )
    )
    await db.commit()

    state = _create_installation_state_token(str(user.id))
    resp = await client.get(
        f"{API}/auth/github/app/callback",
        params={
            "installation_id": 987_654_321,
            "setup_action": "install",
            "state": state,
        },
    )
    assert resp.status_code == 307
    assert "success=true" in resp.headers["location"]

    row = await _user_row(db, user)
    assert row.github_installation_id == 987_654_321

    org = (await db.execute(select(Org).where(Org.name == "test-user"))).scalar_one()
    members = await _members(db, org)
    assert [m.role for m in members] == [ROLE_ORG_ADMIN]


async def test_adoption_request_provisions_membership(client, db, user):
    """Any authenticated request heals the link AND its membership row."""
    db.add(
        _installation(
            111_222_333, login="test-user", account_type="User", account_id=ACCOUNT_ID
        )
    )
    await db.commit()
    assert user.github_installation_id is None

    resp = await client.get(
        f"{API}/auth/me", headers=_auth(user.keycloak_id, ("DEVELOPER",))
    )
    assert resp.status_code == 200

    row = await _user_row(db, user)
    assert row.github_installation_id == 111_222_333

    org = (await db.execute(select(Org).where(Org.name == "test-user"))).scalar_one()
    members = await _members(db, org)
    assert [m.role for m in members] == [ROLE_ORG_ADMIN]


# ---------------------------------------------------------------------------
# Dry-run report data (scripts/org_seed_report.py consumes this)
# ---------------------------------------------------------------------------


async def test_seed_report_planned_and_current_state(db):
    # 1) solo org: one linked user -> ORG_ADMIN.
    solo_install = _installation(2001, login="solo-org")
    db.add(solo_install)
    await db.commit()
    await _make_user(db, "kc-solo-user", github_installation_id=2001)
    await provision_installation_org(db, solo_install)

    # 2) team org: two linked users -> all DEVELOPER (no ORG_ADMIN).
    team_install = _installation(2002, login="team-org")
    db.add(team_install)
    await db.commit()
    await _make_user(db, "kc-team-a", github_installation_id=2002)
    await _make_user(db, "kc-team-b", github_installation_id=2002)
    await provision_installation_org(db, team_install)

    # 3) drift org: installation + linked user, but NO member row (broken hook).
    drift_install = _installation(2003, login="drift-org")
    db.add(drift_install)
    db.add(
        Org(
            name="drift-org",
            account_type="Organization",
            installation_id=2003,
        )
    )
    await db.commit()
    await _make_user(db, "kc-drift-user", github_installation_id=2003)
    await db.commit()

    report = await seed_report(db)

    assert report.orgs_table_exists is True
    planned = {entry.name: entry for entry in report.planned}
    assert len(report.planned) == 3

    assert planned["solo-org"].org_exists is True
    assert planned["solo-org"].has_org_admin is True
    assert planned["solo-org"].members[0]["role"] == ROLE_ORG_ADMIN
    assert planned["solo-org"].missing_members == []

    assert planned["team-org"].org_exists is True
    assert planned["team-org"].has_org_admin is False
    assert {m["role"] for m in planned["team-org"].members} == {"DEVELOPER"}

    assert planned["drift-org"].org_exists is True
    assert planned["drift-org"].missing_members == ["kc-drift-user"]

    current = {org["name"]: org for org in report.current}
    assert current["solo-org"]["has_org_admin"] is True
    assert current["team-org"]["has_org_admin"] is False
    assert current["solo-org"]["members"] == ["kc-solo-user"]
