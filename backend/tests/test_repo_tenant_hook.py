"""watched-repos selection + installation webhook -> repo-tenant-service hook.

The hook is BEST-EFFORT by contract: watched_repos saves (and webhook
processing) must always succeed, even when repo-tenant-service is down —
so the tests assert both the transition diff AND the swallow-failure path.
"""

from conftest import make_keycloak_token
from sqlalchemy import select

from app.config import settings
from app.db.models import GitHubInstallation, Repository, WatchedRepo
from app.services import github, repo_tenant

API = settings.API_V1_PREFIX

REPO_ID = 555777
FULL_NAME = "acme/app"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Recorder:
    """Stands in for app.services.repo_tenant — records calls, never network."""

    def __init__(self) -> None:
        self.enables: list[tuple[int, str, object]] = []
        self.disables: list[int] = []
        self.fail_enable = False

    async def enable_repo(self, *, repo_id, full_name, owner_user_id=None):
        if self.fail_enable:
            raise RuntimeError("repo-tenant-service down")
        self.enables.append((repo_id, full_name, owner_user_id))
        return True

    async def disable_repo(self, repo_id):
        self.disables.append(repo_id)
        return True


async def _watched(db, user, *, enabled: bool, repo_id: int = REPO_ID):
    row = WatchedRepo(
        user_id=user.id,
        repo_id=repo_id,
        repo_name=FULL_NAME,
        enabled=enabled,
    )
    db.add(row)
    await db.commit()
    return row


async def _selection(client, user, repos, *, sync=True):
    token = make_keycloak_token(sub=user.keycloak_id, roles=("DEVELOPER",))
    return await client.post(
        f"{API}/github/repos/selection",
        json={"repos": repos, "sync": sync},
        headers=_auth(token),
    )


def _repo_item(enabled: bool, repo_id: int = REPO_ID) -> dict:
    return {"id": repo_id, "name": FULL_NAME, "private": False, "enabled": enabled}


# ── selection endpoint ─────────────────────────────────────────────────────


async def test_enable_fires_on_newly_enabled_repo(client, user, db, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await _selection(client, user, [_repo_item(True)])

    assert resp.status_code == 200
    assert resp.json() == {"saved": True}
    assert len(rec.enables) == 1
    repo_id, full_name, owner_user_id = rec.enables[0]
    assert repo_id == REPO_ID
    assert full_name == FULL_NAME
    assert owner_user_id == user.id
    assert rec.disables == []


async def test_no_calls_when_already_enabled(client, user, db, monkeypatch):
    """Re-saving the same selection must not re-fire (enable is idempotent
    server-side, but the diff keeps the chatter off the wire)."""
    await _watched(db, user, enabled=True)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await _selection(client, user, [_repo_item(True)])

    assert resp.status_code == 200
    assert rec.enables == []
    assert rec.disables == []


async def test_no_calls_when_selecting_a_disabled_repo(client, user, db, monkeypatch):
    """A deselected (never enabled) repo owns no namespace — nothing to do."""
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await _selection(client, user, [_repo_item(False)])

    assert resp.status_code == 200
    assert rec.enables == []
    assert rec.disables == []


async def test_disable_fires_on_deselect(client, user, db, monkeypatch):
    await _watched(db, user, enabled=True)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await _selection(client, user, [_repo_item(False)])

    assert resp.status_code == 200
    assert rec.disables == [REPO_ID]
    assert rec.enables == []


async def test_disable_fires_for_repo_absent_from_sync_payload(client, user, db, monkeypatch):
    """sync=true full-state payload: a watched repo missing from it is
    deselected -> teardown."""
    await _watched(db, user, enabled=True)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await _selection(client, user, [])

    assert resp.status_code == 200
    assert rec.disables == [REPO_ID]


async def test_selection_survives_repo_tenant_failure(client, user, db, monkeypatch):
    """Contract: the selection SAVES even when repo-tenant-service is down."""
    rec = Recorder()
    rec.fail_enable = True
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await _selection(client, user, [_repo_item(True)])

    assert resp.status_code == 200
    assert resp.json() == {"saved": True}

    # the watched row was still persisted
    from sqlalchemy import select

    rows = await db.execute(select(WatchedRepo).where(WatchedRepo.user_id == user.id))
    watched = rows.scalars().one()
    assert watched.enabled is True


# ── installation_repositories/removed webhook ──────────────────────────────


async def test_installation_removal_tears_down_watched_repo(db, user, monkeypatch):
    from app.api.routes.webhooks import _handle_installation_repos_event

    installation = GitHubInstallation(
        app_id=1,
        installation_id=987654321,
        account_id=1,
        account_login="acme",
        account_type="user",
    )
    db.add(installation)
    await db.commit()
    await _watched(db, user, enabled=True)

    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    payload = {
        "action": "removed",
        "installation": {"id": 987654321},
        "repositories_added": [],
        "repositories_removed": [{"id": REPO_ID, "name": FULL_NAME}],
    }
    result = await _handle_installation_repos_event(payload, "delivery-test-1", db)

    assert result["status"] == "success"
    assert rec.disables == [REPO_ID]

    from sqlalchemy import select

    rows = await db.execute(select(WatchedRepo).where(WatchedRepo.user_id == user.id))
    watched = rows.scalars().one()
    assert watched.enabled is False  # review switch off, row kept for audit


async def test_installation_removal_skips_unwatched_repo(db, user, monkeypatch):
    """A repo that was never enabled owns no namespace — no teardown call."""
    from app.api.routes.webhooks import _handle_installation_repos_event

    installation = GitHubInstallation(
        app_id=1,
        installation_id=987654322,
        account_id=1,
        account_login="acme",
        account_type="user",
    )
    db.add(installation)
    await db.commit()

    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    payload = {
        "action": "removed",
        "installation": {"id": 987654322},
        "repositories_added": [],
        "repositories_removed": [{"id": REPO_ID, "name": FULL_NAME}],
    }
    result = await _handle_installation_repos_event(payload, "delivery-test-2", db)

    assert result["status"] == "success"
    assert rec.disables == []


# ── grid toggle paths (enable / disable / PATCH / connect / delete) ────────
#
# Every route that flips watched_repos must mirror the transition to
# repo-tenant-service — not just the selection endpoint. These tests cover
# the gap where the grid toggle created the review switch but never the
# namespace.


async def _repository(
    db, *, github_repo_id: int = REPO_ID, full_name: str = FULL_NAME
) -> Repository:
    """A Repository row + installation whose account matches the `user` fixture."""
    installation = GitHubInstallation(
        app_id=1,
        installation_id=111222001,
        account_id=111222333,  # == conftest user.github_id
        account_login="test-user",
        account_type="User",
    )
    db.add(installation)
    await db.flush()
    repo = Repository(
        installation_id=installation.id,
        github_repo_id=github_repo_id,
        name=full_name.split("/")[-1],
        full_name=full_name,
        private=False,
        default_branch="main",
        enabled=True,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo


def _user_token(user) -> dict[str, str]:
    return _auth(make_keycloak_token(sub=user.keycloak_id, roles=("DEVELOPER",)))


async def test_grid_enable_fires_repo_tenant(client, user, db, monkeypatch):
    repo = await _repository(db)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await client.post(
        f"{API}/repositories/{repo.id}/enable", headers=_user_token(user)
    )

    assert resp.status_code == 200
    assert rec.enables == [(REPO_ID, FULL_NAME, user.id)]
    assert rec.disables == []


async def test_grid_disable_fires_repo_tenant(client, user, db, monkeypatch):
    repo = await _repository(db)
    await _watched(db, user, enabled=True)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await client.post(
        f"{API}/repositories/{repo.id}/disable", headers=_user_token(user)
    )

    assert resp.status_code == 200
    assert rec.disables == [REPO_ID]
    assert rec.enables == []
    rows = await db.execute(select(WatchedRepo).where(WatchedRepo.user_id == user.id))
    assert rows.scalars().one().enabled is False


async def test_grid_enable_noop_when_already_watched(client, user, db, monkeypatch):
    """Re-toggling an already-enabled repo must not re-fire (transition only)."""
    repo = await _repository(db)
    await _watched(db, user, enabled=True)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await client.post(
        f"{API}/repositories/{repo.id}/enable", headers=_user_token(user)
    )

    assert resp.status_code == 200
    assert rec.enables == []
    assert rec.disables == []


async def test_grid_toggle_survives_repo_tenant_failure(client, user, db, monkeypatch):
    """Contract: the toggle SAVES even when repo-tenant-service is down."""
    repo = await _repository(db)
    rec = Recorder()
    rec.fail_enable = True
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await client.post(
        f"{API}/repositories/{repo.id}/enable", headers=_user_token(user)
    )

    assert resp.status_code == 200
    rows = await db.execute(select(WatchedRepo).where(WatchedRepo.user_id == user.id))
    assert rows.scalars().one().enabled is True


async def test_grid_patch_disable_fires_repo_tenant(client, user, db, monkeypatch):
    """PATCH {enabled: false} flips the switch too — teardown must follow."""
    repo = await _repository(db)
    await _watched(db, user, enabled=True)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await client.patch(
        f"{API}/repositories/{repo.id}",
        json={"enabled": False},
        headers=_user_token(user),
    )

    assert resp.status_code == 200
    assert rec.disables == [REPO_ID]
    assert rec.enables == []


async def test_grid_delete_enabled_repo_fires_disable(client, user, db, monkeypatch):
    """Removing an enabled repo must tear its namespace down too."""
    repo = await _repository(db)
    await _watched(db, user, enabled=True)
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await client.delete(
        f"{API}/repositories/{repo.id}", headers=_user_token(user)
    )

    assert resp.status_code == 204
    assert rec.disables == [REPO_ID]


async def test_connect_fires_repo_tenant(client, user, db, monkeypatch):
    """Connect creates the watched row enabled — the namespace must follow."""
    installation = GitHubInstallation(
        app_id=1,
        installation_id=111222002,
        account_id=111222333,
        account_login="test-user",
        account_type="User",
    )
    db.add(installation)
    await db.commit()

    async def fake_get_installed_repos(installation_id):
        return [
            {
                "id": REPO_ID,
                "name": "app",
                "full_name": FULL_NAME,
                "private": False,
                "default_branch": "main",
            }
        ]

    monkeypatch.setattr(
        github.github_service, "get_installed_repos", fake_get_installed_repos
    )
    rec = Recorder()
    monkeypatch.setattr(repo_tenant, "enable_repo", rec.enable_repo)
    monkeypatch.setattr(repo_tenant, "disable_repo", rec.disable_repo)

    resp = await client.post(
        f"{API}/repositories/connect?github_repo_id={REPO_ID}",
        headers=_user_token(user),
    )

    assert resp.status_code == 201
    assert rec.enables == [(REPO_ID, FULL_NAME, user.id)]
    assert rec.disables == []
