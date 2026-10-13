"""GET /repositories visibility: repo-scoped grants, not bare membership.

Regression history: the list once filtered only
``GitHubInstallation.account_id == current_user.github_id``, so an invited
member who did not install the GitHub App (github_id ≠ account_id) got an
empty list — fixed by adding the org-membership branch (F3). That branch
over-corrected: ANY ``org_members`` row exposed EVERY repository of the
org's installation, ignoring the per-repo grants a repo-scoped invitation
writes (``org_member_repos``, migration 019).

The contract now (``app/services/repository_visibility.py``):

* personal — installations owned by the caller's GitHub account;
* organization — live-member orgs where the caller administers the org
  (effective role ORG_ADMIN, incl. the global-role floor) **or** holds an
  explicit ``org_member_repos`` grant;
* all (default union) — what the SPA's owner/name resolution needs:
  granted repositories resolve, ungranted ones 404.

Read guards on ``GET /repositories/{id}``, ``/{id}/detail`` and
``GET /pull-requests/repository/{id}`` enforce the same boundary.
"""

from types import SimpleNamespace

from conftest import make_keycloak_token

from app.config import settings
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    OrgMemberRepo,
    Repository,
    User,
    WatchedRepo,
)

API = settings.API_V1_PREFIX

# The user fixture carries github_id=111222333.
INSTALLER_GITHUB_ID = 111222333
OTHER_ACCOUNT_ID = 777_777
ALPHA_ACCOUNT_ID = 900_001
SOLO_ACCOUNT_ID = 900_002


def _auth(
    keycloak_id: str = "kc-sub-test-user", roles: tuple[str, ...] = ("DEVELOPER",)
):
    return {
        "Authorization": f"Bearer {make_keycloak_token(sub=keycloak_id, roles=roles)}"
    }


async def _make_user(
    db, keycloak_id: str, *, role: str = "DEVELOPER", github_id: int | None = None
) -> User:
    row = User(
        keycloak_id=keycloak_id, login=keycloak_id, role=role, github_id=github_id
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _seed_installation(
    db,
    *,
    installation_id: int,
    account_id: int,
    account_login: str,
    account_type: str = "Organization",
) -> GitHubInstallation:
    installation = GitHubInstallation(
        app_id=1,
        installation_id=installation_id,
        account_id=account_id,
        account_login=account_login,
        account_type=account_type,
    )
    db.add(installation)
    await db.flush()
    return installation


async def _seed_repo(
    db, installation: GitHubInstallation, github_repo_id: int, name: str
) -> Repository:
    repository = Repository(
        installation_id=installation.id,
        github_repo_id=github_repo_id,
        name=name,
        full_name=f"{installation.account_login}/{name}",
    )
    db.add(repository)
    await db.flush()
    return repository


async def _seed_org(db, installation: GitHubInstallation) -> Org:
    org = Org(
        name=installation.account_login,
        account_type=installation.account_type,
        installation_id=installation.installation_id,
    )
    db.add(org)
    await db.flush()
    return org


async def _grant(
    db, org: Org, user: User, repo: Repository, role: str = "REVIEWER"
) -> None:
    db.add(OrgMemberRepo(org_id=org.id, user_id=user.id, repo_id=repo.id, role=role))
    # Grants only ever come from accepted invitations — which also turn the
    # per-user review switch on for the granted repository.
    db.add(
        WatchedRepo(
            user_id=user.id,
            repo_id=repo.github_repo_id,
            repo_name=repo.full_name,
            enabled=True,
        )
    )
    await db.flush()


async def _alpha_fixture(db):
    """Organization Alpha with four repositories (the task's example)."""
    installation = await _seed_installation(
        db,
        installation_id=5_555_001,
        account_id=ALPHA_ACCOUNT_ID,
        account_login="alpha",
    )
    repos = {
        name: await _seed_repo(db, installation, 600_000 + i, name)
        for i, name in enumerate(("api", "web", "infrastructure", "internal-tools"))
    }
    org = await _seed_org(db, installation)
    await db.commit()
    for repo in repos.values():
        await db.refresh(repo)
    await db.refresh(org)
    return SimpleNamespace(installation=installation, org=org, repos=repos)


async def _grant_reviewer(db, alpha, reviewer: User, names: tuple[str, ...]):
    db.add(OrgMember(org_id=alpha.org.id, user_id=reviewer.id, role="REVIEWER"))
    for name in names:
        await _grant(db, alpha.org, reviewer, alpha.repos[name])
    await db.commit()


# --- list scope ------------------------------------------------------------


async def test_member_without_grants_sees_nothing(client, db, user):
    """Bare membership must not expose the org's repositories."""
    alpha = await _alpha_fixture(db)
    db.add(OrgMember(org_id=alpha.org.id, user_id=user.id, role="REVIEWER"))
    await db.commit()

    for visibility in (None, "all", "organization"):
        params = {"per_page": 100}
        if visibility:
            params["visibility"] = visibility
        resp = await client.get(f"{API}/repositories", params=params, headers=_auth())
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["total"] == 0

    # The SPA's owner/name resolution path — ungranted repos stay unresolvable.
    resp = await client.get(
        f"{API}/repositories",
        params={"search": "alpha/api", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_granted_reviewer_sees_only_granted_repositories(client, db, user):
    """The task's example: invited on api+web, the other repos stay hidden."""
    alpha = await _alpha_fixture(db)
    await _grant_reviewer(db, alpha, user, ("api", "web"))

    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth()
    )
    assert resp.status_code == 200
    assert sorted(r["full_name"] for r in resp.json()["items"]) == [
        "alpha/api",
        "alpha/web",
    ]

    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert sorted(r["full_name"] for r in items) == ["alpha/api", "alpha/web"]
    assert {r["org_id"] for r in items} == {str(alpha.org.id)}
    assert {r["org_name"] for r in items} == {"alpha"}

    # personal collection of a reviewer who owns no installation: empty.
    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "personal", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    # The SPA's owner/name resolution works for granted repos only.
    resp = await client.get(
        f"{API}/repositories",
        params={"search": "alpha/api", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["items"][0]["full_name"] == "alpha/api"

    resp = await client.get(
        f"{API}/repositories",
        params={"search": "alpha/internal-tools", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_ungranted_repository_is_not_directly_readable(client, db, user):
    """Direct by-UUID reads (and PR listings) cannot bypass the grants."""
    alpha = await _alpha_fixture(db)
    await _grant_reviewer(db, alpha, user, ("api",))

    granted = alpha.repos["api"]
    ungranted = alpha.repos["infrastructure"]

    resp = await client.get(f"{API}/repositories/{granted.id}", headers=_auth())
    assert resp.status_code == 200

    resp = await client.get(f"{API}/repositories/{ungranted.id}", headers=_auth())
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Repository not found"

    resp = await client.get(
        f"{API}/repositories/{ungranted.id}/detail", headers=_auth()
    )
    assert resp.status_code == 404

    resp = await client.get(
        f"{API}/pull-requests/repository/{granted.id}", headers=_auth()
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    resp = await client.get(
        f"{API}/pull-requests/repository/{ungranted.id}", headers=_auth()
    )
    assert resp.status_code == 404


async def test_org_admin_sees_all_org_repositories(client, db, user):
    """Requirement: admins keep managing their organization's repositories."""
    alpha = await _alpha_fixture(db)
    db.add(OrgMember(org_id=alpha.org.id, user_id=user.id, role="ORG_ADMIN"))
    await db.commit()

    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    names = {r["full_name"] for r in resp.json()["items"]}
    assert names == {
        "alpha/api",
        "alpha/web",
        "alpha/infrastructure",
        "alpha/internal-tools",
    }


async def test_global_org_admin_does_not_widen_org_repository_visibility(client, db):
    """User-confirmed rule (2026-10-09): a global ORG_ADMIN — which is what
    every GitHub-broker signup derives without an explicit claim — must NOT
    see an org's repositories beyond their grants. Treating it as a floor
    (decisions §11) handed an invited REVIEWER the inviter's whole
    organization; the inviter's org-scoped role selection is the boundary.
    """
    # REVIEWER membership, grant on exactly one repository.
    reviewer = await _make_user(db, "kc-vis-floor", role="ORG_ADMIN")
    alpha = await _alpha_fixture(db)
    db.add(OrgMember(org_id=alpha.org.id, user_id=reviewer.id, role="REVIEWER"))
    await _grant(db, alpha.org, reviewer, alpha.repos["api"])
    await db.commit()

    # Token carries ORG_ADMIN (explicit claim or the broker default —
    # derive_role returns ORG_ADMIN either way); membership row says REVIEWER.
    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=_auth("kc-vis-floor", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 200
    assert [r["full_name"] for r in resp.json()["items"]] == ["alpha/api"]

    # The union (owner/name resolution) is grant-scoped identically.
    resp = await client.get(
        f"{API}/repositories",
        params={"per_page": 100},
        headers=_auth("kc-vis-floor", ("ORG_ADMIN",)),
    )
    assert [r["full_name"] for r in resp.json()["items"]] == ["alpha/api"]

    # An ungranted org repository is not directly readable either.
    ungranted = alpha.repos["infrastructure"]
    resp = await client.get(
        f"{API}/repositories/{ungranted.id}",
        headers=_auth("kc-vis-floor", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 404

    # Without a membership row the global role grants nothing (no org = no floor).
    loner = await _make_user(db, "kc-vis-loner", role="ORG_ADMIN")
    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=_auth("kc-vis-loner", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert loner is not None


async def test_org_admin_membership_still_sees_all_org_repositories(client, db):
    """The explicit org-scoped ORG_ADMIN membership keeps full visibility —
    the provisioning seed (auto-created install org) and invitation
    acceptance both write that row, so real org admins are unaffected."""
    admin = await _make_user(db, "kc-vis-admin", role="ORG_ADMIN")
    alpha = await _alpha_fixture(db)
    db.add(OrgMember(org_id=alpha.org.id, user_id=admin.id, role="ORG_ADMIN"))
    await db.commit()

    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=_auth("kc-vis-admin", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 4


async def test_stale_grant_without_membership_is_dead(client, db, user):
    """A removed member's old org_member_repos rows grant nothing."""
    from sqlalchemy import delete as sa_delete

    alpha = await _alpha_fixture(db)
    await _grant_reviewer(db, alpha, user, ("api", "web"))
    await db.execute(
        sa_delete(OrgMember).where(
            OrgMember.org_id == alpha.org.id, OrgMember.user_id == user.id
        )
    )
    await db.commit()

    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth()
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_personal_repositories_stay_separate_from_organization(client, db):
    """A user with their own installation AND a granted membership sees each
    collection in its own scope — never mixed, never duplicated."""
    solo = await _make_user(
        db, "kc-vis-solo", role="DEVELOPER", github_id=SOLO_ACCOUNT_ID
    )
    own_installation = await _seed_installation(
        db,
        installation_id=5_555_002,
        account_id=SOLO_ACCOUNT_ID,
        account_login="solo",
        account_type="User",
    )
    own_repo = await _seed_repo(db, own_installation, 700_001, "pet")
    own_org = await _seed_org(db, own_installation)
    # Provisioning seeds the installer as ORG_ADMIN of their account's org.
    db.add(OrgMember(org_id=own_org.id, user_id=solo.id, role="ORG_ADMIN"))

    alpha = await _alpha_fixture(db)
    db.add(OrgMember(org_id=alpha.org.id, user_id=solo.id, role="REVIEWER"))
    await _grant(db, alpha.org, solo, alpha.repos["api"])
    await db.commit()
    await db.refresh(own_repo)

    headers = _auth("kc-vis-solo")

    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "personal", "per_page": 100},
        headers=headers,
    )
    assert [r["full_name"] for r in resp.json()["items"]] == ["solo/pet"]

    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=headers,
    )
    assert [r["full_name"] for r in resp.json()["items"]] == ["alpha/api"]

    # The union (owner/name resolution) carries both, without duplicates.
    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=headers
    )
    assert sorted(r["full_name"] for r in resp.json()["items"]) == [
        "alpha/api",
        "solo/pet",
    ]
    # Attribution is viewer-independent: the personal repo carries its own
    # installation's org, the granted one the granting org.
    by_name = {r["full_name"]: r for r in resp.json()["items"]}
    assert by_name["solo/pet"]["org_id"] == str(own_org.id)
    assert by_name["alpha/api"]["org_id"] == str(alpha.org.id)


async def test_github_connection_does_not_broaden_grants(client, db):
    """Linking one's own GitHub App installation adds personal repositories
    only — the other org's ungranted repositories stay invisible."""
    reviewer = await _make_user(
        db, "kc-vis-linked", role="REVIEWER", github_id=SOLO_ACCOUNT_ID
    )
    alpha = await _alpha_fixture(db)
    await _grant_reviewer(db, alpha, reviewer, ("api",))

    own = await _seed_installation(
        db,
        installation_id=5_555_003,
        account_id=SOLO_ACCOUNT_ID,
        account_login="reviewer",
        account_type="User",
    )
    await _seed_repo(db, own, 800_001, "scratch")
    # The GitHub App link itself (what the brokered GitHub login writes).
    reviewer.github_installation_id = own.installation_id
    await db.commit()

    resp = await client.get(
        f"{API}/repositories",
        params={"per_page": 100},
        headers=_auth("kc-vis-linked"),
    )
    assert resp.status_code == 200
    assert sorted(r["full_name"] for r in resp.json()["items"]) == [
        "alpha/api",
        "reviewer/scratch",
    ]

    # The org collection still carries exactly the invitation's grant.
    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=_auth("kc-vis-linked"),
    )
    assert [r["full_name"] for r in resp.json()["items"]] == ["alpha/api"]


async def test_multi_org_user_sees_only_their_grants_per_org(client, db, user):
    """Grants from two orgs union; each org still hides its ungranted repos."""
    alpha = await _alpha_fixture(db)
    await _grant_reviewer(db, alpha, user, ("api",))

    beta_installation = await _seed_installation(
        db, installation_id=5_555_004, account_id=900_003, account_login="beta"
    )
    beta_api = await _seed_repo(db, beta_installation, 610_001, "api")
    beta_secret = await _seed_repo(db, beta_installation, 610_002, "secret")
    beta = await _seed_org(db, beta_installation)
    db.add(OrgMember(org_id=beta.id, user_id=user.id, role="DEVELOPER"))
    await _grant(db, beta, user, beta_api, role="DEVELOPER")
    await db.commit()
    await db.refresh(beta_api)
    await db.refresh(beta_secret)

    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "organization", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    rows = {r["full_name"]: r for r in resp.json()["items"]}
    assert set(rows) == {"alpha/api", "beta/api"}
    assert rows["beta/api"]["org_id"] == str(beta.id)
    assert "beta/secret" not in rows


# --- pre-existing guarantees that must not regress --------------------------


async def test_non_member_without_matching_github_id_sees_nothing(client, db, user):
    """No membership + foreign installation → empty (no cross-org leak)."""
    await _alpha_fixture(db)  # org exists, but this user is no member

    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth()
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


async def test_installer_still_sees_own_installation(client, db, user):
    """No regression: the GitHub account owning the installation still lists."""
    installation = await _seed_installation(
        db,
        installation_id=5_555_005,
        account_id=INSTALLER_GITHUB_ID,
        account_login="some-owner",
        account_type="User",
    )
    repository = await _seed_repo(db, installation, 4242, "demo")
    await db.commit()
    await db.refresh(repository)

    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth()
    )
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()["items"]] == [str(repository.id)]

    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "personal", "per_page": 100},
        headers=_auth(),
    )
    assert [r["id"] for r in resp.json()["items"]] == [str(repository.id)]


async def test_platform_admin_sees_every_repository(client, db):
    """PLATFORM_ADMIN bypasses the membership/grant branches (F2 read)."""
    await _alpha_fixture(db)  # foreign account, no membership, no grants
    admin = await _make_user(db, "kc-vis-pa", role="PLATFORM_ADMIN")

    resp = await client.get(
        f"{API}/repositories",
        params={"per_page": 100},
        headers=_auth("kc-vis-pa", ("PLATFORM_ADMIN",)),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 4
    assert admin is not None


async def test_unknown_visibility_is_rejected(client, db, user):
    resp = await client.get(
        f"{API}/repositories",
        params={"visibility": "bogus"},
        headers=_auth(),
    )
    assert resp.status_code == 422
