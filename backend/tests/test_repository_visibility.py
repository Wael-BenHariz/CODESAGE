"""GET /repositories visibility: org members see their org's installations.

Regression for the reviewer 404: the list filtered
``GitHubInstallation.account_id == current_user.github_id``, so a member who
did not install the GitHub App (github_id ≠ account_id) got an empty list —
the SPA's owner/name resolution found no match, requested the nil-UUID to
surface a genuine 404, and every owner/repo deep link showed "not found".
"""

from conftest import make_keycloak_token

from app.config import settings
from app.db.models import GitHubInstallation, Org, OrgMember, Repository

API = settings.API_V1_PREFIX

# The user fixture carries github_id=111222333.
INSTALLER_GITHUB_ID = 111222333
OTHER_ACCOUNT_ID = 777_777
INSTALLATION_NUMBER = 5_555_555


def _auth(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or make_keycloak_token()}"}


async def _seed_repo(db, *, account_id: int = OTHER_ACCOUNT_ID):
    installation = GitHubInstallation(
        app_id=1,
        installation_id=INSTALLATION_NUMBER,
        account_id=account_id,
        account_login="some-owner",
        account_type="User",
    )
    db.add(installation)
    await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=4242,
        name="demo",
        full_name="some-owner/demo",
    )
    db.add(repository)
    await db.commit()
    await db.refresh(repository)
    return installation, repository


async def _seed_org(db, installation) -> Org:
    org = Org(
        name="some-owner",
        account_type="User",
        installation_id=installation.installation_id,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def test_org_member_sees_installation_repositories(client, db, user):
    """A REVIEWER member (github_id mismatch) sees the org's repositories."""
    installation, repository = await _seed_repo(db)
    org = await _seed_org(db, installation)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role="REVIEWER"))
    await db.commit()

    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth()
    )
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()["items"]] == [str(repository.id)]

    # The SPA's owner/name resolution path (search + exact full_name match).
    resp = await client.get(
        f"{API}/repositories",
        params={"search": "some-owner/demo", "per_page": 100},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["full_name"] == "some-owner/demo"


async def test_non_member_without_matching_github_id_sees_nothing(client, db, user):
    """No membership + foreign installation → empty (no cross-org leak)."""
    installation, _repository = await _seed_repo(db)
    await _seed_org(db, installation)  # org exists, but this user is no member

    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth()
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


async def test_installer_still_sees_own_installation(client, db, user):
    """No regression: the GitHub account owning the installation still lists."""
    _installation, repository = await _seed_repo(db, account_id=INSTALLER_GITHUB_ID)

    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth()
    )
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()["items"]] == [str(repository.id)]


async def test_platform_admin_sees_every_repository(client, db, user):
    """PLATFORM_ADMIN bypasses both branches (F2 read, mirrors GET /reviews)."""
    _installation, repository = await _seed_repo(db)  # foreign account, no membership

    token = make_keycloak_token(roles=("PLATFORM_ADMIN",))
    resp = await client.get(
        f"{API}/repositories", params={"per_page": 100}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()["items"]] == [str(repository.id)]
