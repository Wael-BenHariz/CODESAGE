"""Phase 7 — workspace RBAC matrix (target design §2.3 / §2.5).

Contracts covered here:

- ``GET /auth/me`` carries per-workspace *effective* roles plus capability
  flags (the frontend renders from those, never from role lists).
- GitHub App install-url: ``workspace_id`` gate (``repo_admin`` =
  ORG_ADMIN+, unknown workspace / non-member → uniform 404) and the
  chosen workspace is signed into the state token (``wid``).
- Shared state gate (§2.5): validate / dismiss / restore / summary-edit
  are blocked once posted and outside the ``ready_to_post`` state (409).
- Pending dismissal requests block posting until resolved (409).
- Self-review rule (§2.5): in a multi-member ORG workspace the PR author
  may not validate/dismiss/approve their own findings; disabled for
  PERSONAL workspaces and single-member ORG workspaces.
- Repo matrix (§2.3): PATCH/enable = ``repo_config`` (REVIEWER+),
  DELETE = ``repo_admin`` (ORG_ADMIN+), connect gated per workspace.
- Workspace routes: uniform 404 for non-members, PLATFORM_ADMIN may
  read/settings anywhere (§2.3 matrix-Y), member-role writes land in
  BOTH membership tables, last-admin and repo-holding delete guards,
  personal workspaces are not deletable.
- Notifications: strictly scoped to the caller; workspace filter needs
  membership.
- Install requests: ``trigger`` to create (org admins notified in-app),
  ``repo_admin`` to approve; dismissal requests: ``request`` to create,
  ``review`` to approve with posted/self-review guards.
- Provisioning: an org gets an ORG workspace, the installation is
  stamped, members are mirrored into ``workspace_members``; webhook
  ``installation`` events stamp the workspace down to new repos.
"""

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest_asyncio
from jose import jwt as jose_jwt
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from test_review_api_staged import _auth, _comment_of, _make_user, _patch_github

from app.config import settings
from app.db.models import (
    GitHubInstallation,
    Notification,
    Org,
    OrgMember,
    PullRequest,
    Repository,
    Review,
    ReviewComment,
    Workspace,
    WorkspaceMember,
)
from app.services import github_service
from app.services.org_provisioning import mirror_org_members, provision_installation_org

API = settings.API_V1_PREFIX
_WS = f"{API}/workspaces"
_REPOS = f"{API}/repositories"
_REVIEWS = f"{API}/reviews"
_DISMISSALS = f"{API}/dismissal-requests"
_INSTALL_REQS = f"{API}/install-requests"
_NOTIFICATIONS = f"{API}/notifications"
_INSTALL_URL = f"{API}/auth/github/app/install-url"

_INSTALLATION_ID = 888001
_GH_REPO_ID = 555001


async def _build_rbac_workspace(db) -> SimpleNamespace:
    """One ORG workspace bound to org + installation + repo + PR + review.

    Members live in BOTH membership tables with the same role, except the
    NONE sentinel which ``org_members`` cannot store.
    """
    users = {
        "admin": await _make_user(db, "kc-rbac-admin", role="DEVELOPER"),
        "reviewer": await _make_user(db, "kc-rbac-reviewer", role="DEVELOPER"),
        "dev": await _make_user(db, "kc-rbac-dev", role="DEVELOPER"),
        "alice": await _make_user(db, "kc-rbac-alice", role="DEVELOPER"),
        "outsider": await _make_user(db, "kc-rbac-outsider", role="DEVELOPER"),
        "pa": await _make_user(db, "kc-rbac-pa", role="PLATFORM_ADMIN"),
        "none": await _make_user(db, "kc-rbac-none", role="NONE"),
    }

    ws_org = Workspace(
        type="ORG",
        name="acme",
        github_account_login="Organization:acme",
    )
    db.add(ws_org)
    await db.flush()

    installation = GitHubInstallation(
        app_id=1,
        installation_id=_INSTALLATION_ID,
        account_id=9001,
        account_login="acme",
        account_type="Organization",
        workspace_id=ws_org.id,
    )
    db.add(installation)
    await db.flush()

    org = Org(
        name="acme",
        account_type="Organization",
        installation_id=_INSTALLATION_ID,
        workspace_id=ws_org.id,
    )
    db.add(org)
    await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=_GH_REPO_ID,
        name="demo",
        full_name="acme/demo",
        workspace_id=ws_org.id,
    )
    db.add(repository)
    await db.flush()

    pr = PullRequest(
        repository_id=repository.id,
        github_pr_id=11,
        number=11,
        title="Change",
        author_login=users["alice"].login,  # self-review rule compares logins
        base_branch="main",
        head_branch="feature",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    db.add(pr)
    await db.flush()

    now = datetime.now(timezone.utc)
    review = Review(
        pull_request_id=pr.id,
        status="ready_to_post",
        posting_mode="staged",
        summary="Looks fine.",
        started_at=now,
        completed_at=now,
        workspace_id=ws_org.id,
    )
    db.add(review)
    await db.flush()

    db.add_all(
        [
            ReviewComment(
                review_id=review.id,
                pull_request_id=pr.id,
                file_path="src/a.py",
                line_number=1,
                body="Dangerous call",
                severity="error",
                category="bug",
            ),
            ReviewComment(
                review_id=review.id,
                pull_request_id=pr.id,
                file_path="src/b.py",
                line_number=2,
                body="Naming nit",
                severity="info",
                category="style",
            ),
        ]
    )

    memberships = {
        "admin": "ORG_ADMIN",
        "reviewer": "REVIEWER",
        "dev": "DEVELOPER",
        "alice": "REVIEWER",
        "none": "NONE",
    }
    for key, role in memberships.items():
        db.add(
            WorkspaceMember(workspace_id=ws_org.id, user_id=users[key].id, role=role)
        )
        if role != "NONE":  # org_members cannot store the NONE sentinel
            db.add(OrgMember(org_id=org.id, user_id=users[key].id, role=role))

    # dev's personal workspace (owner is ORG_ADMIN there by definition).
    ws_personal = Workspace(
        type="PERSONAL",
        name="dev personal",
        owner_user_id=users["dev"].id,
    )
    db.add(ws_personal)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=ws_personal.id,
            user_id=users["dev"].id,
            role="ORG_ADMIN",
        )
    )

    await db.commit()
    await db.refresh(review, ["comments"])

    return SimpleNamespace(
        ws_org=ws_org,
        ws_personal=ws_personal,
        org=org,
        installation=installation,
        repo=repository,
        pr=pr,
        review=review,
        users=users,
    )


@pytest_asyncio.fixture
async def rbac(db):
    return await _build_rbac_workspace(db)


# ---------------------------------------------------------------------------
# GET /auth/me — per-workspace effective roles + capabilities
# ---------------------------------------------------------------------------


async def test_me_lists_workspaces_with_effective_roles_and_capabilities(client, rbac):
    resp = await client.get(f"{API}/auth/me", headers=_auth("kc-rbac-dev"))
    assert resp.status_code == 200
    body = resp.json()

    by_id = {w["id"]: w for w in body["workspaces"]}
    assert set(by_id) == {str(rbac.ws_org.id), str(rbac.ws_personal.id)}

    personal = by_id[str(rbac.ws_personal.id)]
    assert personal["is_personal"] is True
    assert personal["role"] == "ORG_ADMIN"
    assert personal["capabilities"]["repo_admin"] is True
    assert personal["capabilities"]["platform"] is False

    org_ws = by_id[str(rbac.ws_org.id)]
    assert org_ws["is_personal"] is False
    assert org_ws["role"] == "DEVELOPER"
    assert org_ws["capabilities"]["trigger"] is True
    assert org_ws["capabilities"]["review"] is False
    assert org_ws["capabilities"]["platform"] is False

    # Global capabilities mirror the realm role's flags (DEVELOPER here).
    assert body["capabilities"]["view"] is True
    assert body["capabilities"]["review"] is False
    assert body["capabilities"]["platform"] is False


async def test_me_for_none_role_is_view_only(client, rbac):
    resp = await client.get(f"{API}/auth/me", headers=_auth("kc-rbac-none", ("NONE",)))
    assert resp.status_code == 200
    body = resp.json()

    assert body["capabilities"]["view"] is True
    assert body["capabilities"]["trigger"] is False
    assert body["capabilities"]["review"] is False

    org_ws = next(w for w in body["workspaces"] if w["id"] == str(rbac.ws_org.id))
    assert org_ws["role"] == "NONE"
    assert org_ws["capabilities"]["view"] is True
    assert org_ws["capabilities"]["review"] is False


# ---------------------------------------------------------------------------
# Install-url — workspace_id gate + signed wid (§2.5 request-install flow)
# ---------------------------------------------------------------------------


async def test_install_url_non_member_workspace_is_404(client, rbac):
    resp = await client.get(
        f"{_INSTALL_URL}?workspace_id={rbac.ws_org.id}",
        headers=_auth("kc-rbac-outsider"),
    )
    assert resp.status_code == 404


async def test_install_url_developer_is_403(client, rbac):
    """Installing the App is repo_admin (ORG_ADMIN+) in the target workspace."""
    resp = await client.get(
        f"{_INSTALL_URL}?workspace_id={rbac.ws_org.id}",
        headers=_auth("kc-rbac-dev"),
    )
    assert resp.status_code == 403


async def test_install_url_org_admin_state_carries_wid(client, rbac, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_SLUG", "codesage-test")
    resp = await client.get(
        f"{_INSTALL_URL}?workspace_id={rbac.ws_org.id}",
        headers=_auth("kc-rbac-admin"),
    )
    assert resp.status_code == 200
    url = resp.json()["url"]
    assert "/apps/codesage-test/installations/new" in url

    state = parse_qs(urlparse(url).query)["state"][0]
    payload = jose_jwt.decode(
        state, settings.STATE_TOKEN_SECRET, algorithms=[settings.ALGORITHM]
    )
    assert payload["type"] == "github_app_installation_state"
    assert payload["wid"] == str(rbac.ws_org.id)
    assert payload["sub"] == str(rbac.users["admin"].id)


async def test_install_url_without_workspace_is_unbound(client, rbac, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_SLUG", "codesage-test")
    resp = await client.get(_INSTALL_URL, headers=_auth("kc-rbac-dev"))
    assert resp.status_code == 200

    state = parse_qs(urlparse(resp.json()["url"]).query)["state"][0]
    payload = jose_jwt.decode(
        state, settings.STATE_TOKEN_SECRET, algorithms=[settings.ALGORITHM]
    )
    assert "wid" not in payload  # legacy flow: no workspace binding


# ---------------------------------------------------------------------------
# §2.5 shared state gate — posted (or not ready) blocks finding actions
# ---------------------------------------------------------------------------


async def test_dismiss_and_restore_blocked_once_posted(client, rbac, db):
    rbac.review.posted_at = datetime.now(timezone.utc)
    await db.commit()

    comment = _comment_of(rbac.review, severity="error")
    headers = _auth("kc-rbac-reviewer")
    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/dismiss",
        headers=headers,
    )
    assert resp.status_code == 409

    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/restore",
        headers=headers,
    )
    assert resp.status_code == 409


async def test_validate_blocked_once_posted(client, rbac, db):
    rbac.review.posted_at = datetime.now(timezone.utc)
    await db.commit()

    comment = _comment_of(rbac.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/validate",
        json={"verdict": "confirmed"},
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 409


async def test_dismiss_blocked_outside_ready_state(client, rbac, db):
    rbac.review.status = "processing"
    await db.commit()

    comment = _comment_of(rbac.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/dismiss",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 409


async def test_summary_edit_blocked_outside_ready_state(client, rbac, db):
    rbac.review.status = "completed"
    await db.commit()

    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/summary",
        json={"summary": "Edited."},
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Posting blocked while a dismissal request is pending (§2.5)
# ---------------------------------------------------------------------------


async def test_post_blocked_while_dismissal_request_pending(client, rbac, monkeypatch):
    stub = _patch_github(monkeypatch)
    comment = _comment_of(rbac.review, severity="error")

    # A DEVELOPER asks for the finding to be dismissed.
    resp = await client.post(
        _DISMISSALS,
        params={
            "review_comment_id": str(comment.id),
            "reason": "false alarm",
        },
        headers=_auth("kc-rbac-dev"),
    )
    assert resp.status_code == 201
    request_id = resp.json()["id"]

    # Posting is blocked while the request is unresolved — nothing hits GitHub.
    resp = await client.post(
        f"{_REVIEWS}/{rbac.review.id}/post",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 409
    assert stub.calls == []

    # A REVIEWER resolves it (approve also dismisses the finding)…
    resp = await client.patch(
        f"{_DISMISSALS}/{request_id}/approve",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"

    # …and posting now goes through.
    resp = await client.post(
        f"{_REVIEWS}/{rbac.review.id}/post",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 200
    assert len(stub.calls) == 1


# ---------------------------------------------------------------------------
# Dismissal request matrix — create = request (DEVELOPER+),
# approve = review (REVIEWER+) with posted + self-review guards
# ---------------------------------------------------------------------------


async def test_dismissal_request_create_and_approve_matrix(client, rbac, db):
    comment = _comment_of(rbac.review, severity="info")
    params = {"review_comment_id": str(comment.id), "reason": "noise"}

    # NONE cannot even ask (request permission floor).
    resp = await client.post(
        _DISMISSALS, params=params, headers=_auth("kc-rbac-none", ("NONE",))
    )
    assert resp.status_code == 403

    # A DEVELOPER member can ask.
    resp = await client.post(_DISMISSALS, params=params, headers=_auth("kc-rbac-dev"))
    assert resp.status_code == 201
    request_id = resp.json()["id"]

    # Approving needs REVIEWER+ — a DEVELOPER member is 403.
    resp = await client.patch(
        f"{_DISMISSALS}/{request_id}/approve",
        headers=_auth("kc-rbac-dev"),
    )
    assert resp.status_code == 403

    # The PR author may not approve findings on their own PR (§2.5).
    resp = await client.patch(
        f"{_DISMISSALS}/{request_id}/approve",
        headers=_auth("kc-rbac-alice"),
    )
    assert resp.status_code == 403

    # A REVIEWER member approves: request resolved + finding dismissed.
    resp = await client.patch(
        f"{_DISMISSALS}/{request_id}/approve",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"

    # Column-level select: the fixture session still holds the pre-approve
    # comment object in its identity map (the API committed in its own).
    dismissed = (
        await db.execute(
            select(ReviewComment.dismissed).where(ReviewComment.id == comment.id)
        )
    ).scalar_one()
    assert dismissed is True

    # Resolving twice is a conflict.
    resp = await client.patch(
        f"{_DISMISSALS}/{request_id}/approve",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Self-review rule (§2.5)
# ---------------------------------------------------------------------------


async def test_author_cannot_validate_or_dismiss_own_pr(client, rbac):
    comment = _comment_of(rbac.review, severity="error")

    # alice is a REVIEWER — the 403 comes from the self-review rule, not
    # from a missing permission floor.
    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/validate",
        json={"verdict": "confirmed"},
        headers=_auth("kc-rbac-alice"),
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/dismiss",
        headers=_auth("kc-rbac-alice"),
    )
    assert resp.status_code == 403

    # Control: any other REVIEWER validates and dismisses without friction.
    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/validate",
        json={"verdict": "confirmed"},
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 200

    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/dismiss",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 200


async def test_self_review_disabled_single_member_org_workspace(client, rbac, db):
    # Reduce the ORG workspace to alice alone (both tables).
    await db.execute(
        sa_delete(WorkspaceMember).where(
            WorkspaceMember.workspace_id == rbac.ws_org.id,
            WorkspaceMember.user_id != rbac.users["alice"].id,
        )
    )
    await db.execute(
        sa_delete(OrgMember).where(
            OrgMember.org_id == rbac.org.id,
            OrgMember.user_id != rbac.users["alice"].id,
        )
    )
    await db.commit()

    comment = _comment_of(rbac.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/dismiss",
        headers=_auth("kc-rbac-alice"),
    )
    assert resp.status_code == 200


async def test_self_review_disabled_personal_workspace(client, rbac, db):
    # Same PR/review, but its workspace is PERSONAL → rule disabled.
    rbac.review.workspace_id = rbac.ws_personal.id
    await db.commit()

    comment = _comment_of(rbac.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{rbac.review.id}/comments/{comment.id}/validate",
        json={"verdict": "false_positive"},
        headers=_auth("kc-rbac-alice"),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Repo matrix — PATCH/enable = repo_config (REVIEWER+),
# DELETE = repo_admin (ORG_ADMIN+), connect = per-workspace gate
# ---------------------------------------------------------------------------


async def test_repo_patch_requires_reviewer(client, rbac):
    url = f"{_REPOS}/{rbac.repo.id}"

    resp = await client.patch(
        url, json={"default_branch": "develop"}, headers=_auth("kc-rbac-dev")
    )
    assert resp.status_code == 403

    resp = await client.patch(
        url, json={"default_branch": "develop"}, headers=_auth("kc-rbac-reviewer")
    )
    assert resp.status_code == 200
    assert resp.json()["default_branch"] == "develop"


async def test_repo_enable_requires_reviewer(client, rbac):
    resp = await client.post(
        f"{_REPOS}/{rbac.repo.id}/enable", headers=_auth("kc-rbac-dev")
    )
    assert resp.status_code == 403


async def test_repo_delete_requires_org_admin(client, rbac):
    resp = await client.delete(
        f"{_REPOS}/{rbac.repo.id}", headers=_auth("kc-rbac-reviewer")
    )
    assert resp.status_code == 403

    resp = await client.delete(
        f"{_REPOS}/{rbac.repo.id}", headers=_auth("kc-rbac-admin")
    )
    assert resp.status_code == 204


async def test_repo_connect_workspace_gate(client, rbac):
    headers = {
        **_auth("kc-rbac-dev"),
        "X-Workspace-Id": str(rbac.ws_org.id),
    }
    resp = await client.post(
        f"{_REPOS}/connect", params={"github_repo_id": 424242}, headers=headers
    )
    assert resp.status_code == 403  # repo_config floor, no GitHub round trip

    headers = {
        **_auth("kc-rbac-outsider"),
        "X-Workspace-Id": str(rbac.ws_org.id),
    }
    resp = await client.post(
        f"{_REPOS}/connect", params={"github_repo_id": 424242}, headers=headers
    )
    assert resp.status_code == 404  # uniform non-member 404


# ---------------------------------------------------------------------------
# Workspace routes
# ---------------------------------------------------------------------------


async def test_workspace_uniform_404_for_non_member(client, rbac):
    resp = await client.get(
        f"{_WS}/{rbac.ws_org.id}", headers=_auth("kc-rbac-outsider")
    )
    assert resp.status_code == 404

    resp = await client.get(f"{_WS}/{rbac.ws_org.id}", headers=_auth("kc-rbac-dev"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "DEVELOPER"
    assert body["capabilities"]["trigger"] is True
    assert body["capabilities"]["repo_config"] is False


async def test_platform_admin_acts_in_any_workspace(client, rbac):
    headers = _auth("kc-rbac-pa", ("PLATFORM_ADMIN",))

    resp = await client.get(f"{_WS}/{rbac.ws_org.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "PLATFORM_ADMIN"

    # §2.3 matrix: PLATFORM_ADMIN is Y on workspace settings too.
    resp = await client.patch(
        f"{_WS}/{rbac.ws_org.id}", params={"name": "acme-renamed"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "acme-renamed"


async def test_member_role_update_writes_both_tables(client, rbac, db):
    url = f"{_WS}/{rbac.ws_org.id}/members/{rbac.users['dev'].id}"

    resp = await client.patch(
        url, params={"role": "REVIEWER"}, headers=_auth("kc-rbac-reviewer")
    )
    assert resp.status_code == 403  # member management = repo_admin

    resp = await client.patch(
        url, params={"role": "REVIEWER"}, headers=_auth("kc-rbac-admin")
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "REVIEWER"

    # Dual-write: both tables carry the new role (reads take the ladder
    # max, so a single-sided write would be cancelled out).
    ws_row = (
        await db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == rbac.ws_org.id,
                WorkspaceMember.user_id == rbac.users["dev"].id,
            )
        )
    ).scalar_one()
    org_row = (
        await db.execute(
            select(OrgMember.role).where(
                OrgMember.org_id == rbac.org.id,
                OrgMember.user_id == rbac.users["dev"].id,
            )
        )
    ).scalar_one()
    assert ws_row == org_row == "REVIEWER"


async def test_last_org_admin_cannot_be_demoted(client, rbac):
    resp = await client.patch(
        f"{_WS}/{rbac.ws_org.id}/members/{rbac.users['admin'].id}",
        params={"role": "DEVELOPER"},
        headers=_auth("kc-rbac-admin"),
    )
    assert resp.status_code == 400


async def test_non_member_target_of_role_update_is_404(client, rbac):
    resp = await client.patch(
        f"{_WS}/{rbac.ws_org.id}/members/{rbac.users['outsider'].id}",
        params={"role": "REVIEWER"},
        headers=_auth("kc-rbac-admin"),
    )
    assert resp.status_code == 404


async def test_delete_workspace_with_repositories_is_409(client, rbac):
    resp = await client.delete(
        f"{_WS}/{rbac.ws_org.id}", headers=_auth("kc-rbac-admin")
    )
    assert resp.status_code == 409


async def test_personal_workspace_is_not_deletable(client, rbac):
    resp = await client.delete(
        f"{_WS}/{rbac.ws_personal.id}", headers=_auth("kc-rbac-dev")
    )
    assert resp.status_code == 400
    assert "personal" in resp.json()["detail"].lower()


async def test_create_org_workspace_requires_global_role(client, rbac):
    resp = await client.post(
        _WS, params={"name": "new-ws"}, headers=_auth("kc-rbac-dev")
    )
    assert resp.status_code == 403

    resp = await client.post(
        _WS,
        params={"name": "new-ws"},
        headers=_auth("kc-rbac-admin", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "ORG"
    assert body["role"] == "ORG_ADMIN"
    assert body["capabilities"]["repo_admin"] is True


# ---------------------------------------------------------------------------
# Notifications — scoped to the caller; workspace filter needs membership
# ---------------------------------------------------------------------------


async def test_notifications_scoped_to_caller_and_workspace(client, rbac, db):
    db.add_all(
        [
            Notification(
                user_id=rbac.users["dev"].id,
                workspace_id=rbac.ws_org.id,
                type="info",
                title="for dev",
            ),
            Notification(
                user_id=rbac.users["admin"].id,
                workspace_id=rbac.ws_org.id,
                type="info",
                title="for admin",
            ),
            Notification(
                user_id=rbac.users["outsider"].id,
                workspace_id=None,
                type="info",
                title="for outsider",
            ),
        ]
    )
    await db.commit()

    resp = await client.get(_NOTIFICATIONS, headers=_auth("kc-rbac-dev"))
    assert resp.status_code == 200
    titles = [n["title"] for n in resp.json()]
    assert titles == ["for dev"]  # never anyone else's rows

    resp = await client.get(
        _NOTIFICATIONS,
        params={"workspace_id": str(rbac.ws_org.id)},
        headers=_auth("kc-rbac-dev"),
    )
    assert resp.status_code == 200
    assert [n["title"] for n in resp.json()] == ["for dev"]

    resp = await client.get(
        _NOTIFICATIONS,
        params={"workspace_id": str(rbac.ws_org.id)},
        headers=_auth("kc-rbac-outsider"),
    )
    assert resp.status_code == 404  # uniform non-member answer


# ---------------------------------------------------------------------------
# Install requests (§2.5) — trigger to create, repo_admin to approve
# ---------------------------------------------------------------------------


async def test_install_request_create_notifies_org_admins(client, rbac, db):
    headers = _auth("kc-rbac-dev")
    resp = await client.post(
        _INSTALL_REQS, params={"workspace_id": str(rbac.ws_org.id)}, headers=headers
    )
    assert resp.status_code == 201
    request_id = resp.json()["id"]

    # The ORG_ADMIN was notified in-app.
    notif = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.user_id == rbac.users["admin"].id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notif) == 1

    # Duplicate pending request → conflict.
    resp = await client.post(
        _INSTALL_REQS, params={"workspace_id": str(rbac.ws_org.id)}, headers=headers
    )
    assert resp.status_code == 409

    # Non-member → 404, NONE → 403 (before any lookup).
    resp = await client.post(
        _INSTALL_REQS,
        params={"workspace_id": str(rbac.ws_org.id)},
        headers=_auth("kc-rbac-outsider"),
    )
    assert resp.status_code == 404

    resp = await client.post(
        _INSTALL_REQS,
        params={"workspace_id": str(rbac.ws_org.id)},
        headers=_auth("kc-rbac-none", ("NONE",)),
    )
    assert resp.status_code == 403

    # Approve = repo_admin: REVIEWER is 403, ORG_ADMIN succeeds.
    resp = await client.patch(
        f"{_INSTALL_REQS}/{request_id}/approve",
        headers=_auth("kc-rbac-reviewer"),
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"{_INSTALL_REQS}/{request_id}/approve",
        headers=_auth("kc-rbac-admin"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Provisioning — ORG workspace + member mirror (dual-read stays aligned)
# ---------------------------------------------------------------------------


async def test_provisioning_creates_org_workspace_and_mirrors_members(db):
    linked = await _make_user(db, "kc-rbac-linked", role="DEVELOPER")
    linked.github_id = 424242
    linked.github_installation_id = 999001

    installation = GitHubInstallation(
        app_id=1,
        installation_id=999001,
        account_id=424242,
        account_login="solo",
        account_type="User",
    )
    db.add(installation)
    await db.commit()

    org = await provision_installation_org(db, installation)
    await db.commit()

    # Org ↔ workspace ↔ installation all point at the same workspace.
    assert org.workspace_id is not None
    ws = (
        await db.execute(select(Workspace).where(Workspace.id == org.workspace_id))
    ).scalar_one()
    assert ws.type == "ORG"
    assert ws.github_account_login == "User:solo"
    assert installation.workspace_id == ws.id

    # The single linked user was seeded ORG_ADMIN and mirrored into
    # workspace_members within the same provisioning call.
    ws_role = (
        await db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == linked.id,
            )
        )
    ).scalar_one_or_none()
    assert ws_role == "ORG_ADMIN"

    org_role = (
        await db.execute(
            select(OrgMember.role).where(
                OrgMember.org_id == org.id,
                OrgMember.user_id == linked.id,
            )
        )
    ).scalar_one()
    assert org_role == "ORG_ADMIN"


async def test_mirror_org_members_is_insert_only(db):
    ws = Workspace(type="ORG", name="drift", github_account_login="Organization:drift")
    db.add(ws)
    await db.flush()
    org = Org(name="drift", account_type="Organization", workspace_id=ws.id)
    db.add(org)
    await db.flush()

    keep = await _make_user(db, "kc-rbac-keep", role="DEVELOPER")
    fresh = await _make_user(db, "kc-rbac-fresh", role="DEVELOPER")

    # Drift: org row says ORG_ADMIN, workspace row says DEVELOPER — the
    # mirror must NOT overwrite the workspace-side row (dual-read takes
    # the ladder max anyway), only fill rows that are missing.
    db.add(OrgMember(org_id=org.id, user_id=keep.id, role="ORG_ADMIN"))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=keep.id, role="DEVELOPER"))
    db.add(OrgMember(org_id=org.id, user_id=fresh.id, role="REVIEWER"))
    await db.commit()

    inserted = await mirror_org_members(db, org)
    await db.commit()
    assert inserted == 1  # only the missing row

    keep_ws = (
        await db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == keep.id,
            )
        )
    ).scalar_one()
    assert keep_ws == "DEVELOPER"  # untouched

    fresh_ws = (
        await db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == fresh.id,
            )
        )
    ).scalar_one()
    assert fresh_ws == "REVIEWER"


# ---------------------------------------------------------------------------
# Webhook — installation event stamps the workspace down to new repos
# ---------------------------------------------------------------------------


async def test_webhook_installation_event_stamps_workspace_chain(client, db):
    payload = {
        "action": "created",
        "installation": {
            "id": 777123,
            "app_id": 12345,
            "account": {"id": 54321, "login": "wh-org", "type": "Organization"},
            "permissions": {"contents": "read"},
        },
        "repositories": [
            {
                "id": 600001,
                "name": "r1",
                "full_name": "wh-org/r1",
                "private": False,
                "default_branch": "main",
            }
        ],
    }
    body = json.dumps(payload).encode()

    resp = await client.post(
        f"{API}/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": github_service.generate_webhook_signature(body),
            "X-GitHub-Event": "installation",
            "X-GitHub-Delivery": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 200

    installation = (
        await db.execute(
            select(GitHubInstallation).where(
                GitHubInstallation.installation_id == 777123
            )
        )
    ).scalar_one()
    assert installation.workspace_id is not None

    ws = (
        await db.execute(
            select(Workspace).where(Workspace.id == installation.workspace_id)
        )
    ).scalar_one()
    assert ws.type == "ORG"
    assert ws.name == "wh-org"

    # The repo created in the same event inherited the binding.
    repo = (
        await db.execute(select(Repository).where(Repository.github_repo_id == 600001))
    ).scalar_one()
    assert repo.workspace_id == installation.workspace_id
