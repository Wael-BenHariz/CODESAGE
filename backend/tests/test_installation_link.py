"""Self-healing ``users.github_installation_id`` link.

The link is normally written by the signed-state install callback. When the
callback never arrives (GitHub App Setup URL unset / redirect aborted), two
independent heal paths keep it true:

1. the ``installation created`` webhook links the account owner directly,
2. ``_authenticate`` adopts the newest installation owned by the user's
   GitHub account on any authenticated request.

Without a link, /github/status reports "not installed", /github/repos 400s,
and PR webhooks are ignored with "no user linked to installation".
"""

from conftest import make_keycloak_token
from sqlalchemy import select

from app.api.routes.webhooks import _handle_installation_event
from app.config import settings
from app.db.models import GitHubInstallation, User

API = settings.API_V1_PREFIX

INSTALLATION_ID = 987654399
# == conftest user.github_id
ACCOUNT_ID = 111222333


def _created_payload(*, account_id: int = ACCOUNT_ID) -> dict:
    return {
        "action": "created",
        "installation": {
            "id": INSTALLATION_ID,
            "app_id": 1,
            "account": {"id": account_id, "login": "test-user", "type": "User"},
            "permissions": {"contents": "read"},
            "events": ["push", "pull_request"],
        },
        "repositories": [
            {"id": 555777, "name": "app", "full_name": "acme/app", "private": False}
        ],
    }


async def _user_row(db, user) -> User:
    # populate_existing: expire_on_commit=False keeps the identity-map object
    # alive, so a plain re-SELECT would serve its stale attributes instead of
    # the row the app session just committed (cross-session writes).
    result = await db.execute(
        select(User).where(User.id == user.id).execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def test_installation_created_links_matching_user(db, user):
    result = await _handle_installation_event(_created_payload(), "delivery-link-1", db)

    assert result["status"] == "success"
    row = await _user_row(db, user)
    assert row.github_installation_id == INSTALLATION_ID


async def test_installation_created_leaves_unknown_account_unlinked(db, user):
    """No user row matches the account -> installation still recorded, link untouched."""
    result = await _handle_installation_event(
        _created_payload(account_id=424242), "delivery-link-2", db
    )

    assert result["status"] == "success"
    row = await _user_row(db, user)
    assert row.github_installation_id is None

    records = await db.execute(
        select(GitHubInstallation).where(
            GitHubInstallation.installation_id == INSTALLATION_ID
        )
    )
    assert records.scalar_one() is not None


async def test_installation_created_updates_stale_link(db, user):
    """`created` is authoritative: a stale link from a missed delete heals."""
    user.github_installation_id = 111111
    await db.commit()

    result = await _handle_installation_event(_created_payload(), "delivery-link-3", db)

    assert result["status"] == "success"
    row = await _user_row(db, user)
    assert row.github_installation_id == INSTALLATION_ID


async def test_auth_request_adopts_installation_link(client, db, user):
    """Any authenticated request heals a NULL link from github_installations."""
    db.add(
        GitHubInstallation(
            app_id=1,
            installation_id=INSTALLATION_ID,
            account_id=ACCOUNT_ID,
            account_login="test-user",
            account_type="User",
        )
    )
    await db.commit()

    token = make_keycloak_token(sub=user.keycloak_id, roles=("DEVELOPER",))
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    row = await _user_row(db, user)
    assert row.github_installation_id == INSTALLATION_ID


async def test_auth_adoption_is_a_noop_without_installation(client, db, user):
    """No installation row and a NULL link -> still a normal 200, no crash."""
    token = make_keycloak_token(sub=user.keycloak_id, roles=("DEVELOPER",))
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    row = await _user_row(db, user)
    assert row.github_installation_id is None
