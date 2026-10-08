"""Repo-scoped invitations (migration 019 + Step 11 follow-up).

One role for a whole selection of repositories — DEVELOPER (GitHub
``push``) or REVIEWER (GitHub ``triage``). Contracts covered here:

- **Create**: ``repository_ids`` are validated against the org's GitHub
  App installation (repo → installation → org chain); an unknown or
  foreign-org id is a 400 *before* anything is persisted; duplicates
  collapse; the response echoes ids + resolved ``owner/repo`` names.
  Org-only invitations (no ``repository_ids``) keep the old behaviour
  (covered in test_invitations_api).
- **Preview / list**: both carry the resolved repository names.
- **Accept**: writes ``org_member_repos`` (role + collaborator outcome)
  and the ``watched_repos`` rows in the same transaction as the
  membership, then runs the **best-effort GitHub collaborator pass**
  (mapped permission, per-repo errors joined onto
  ``org_invitations.github_error``) — a failure never fails the accept —
  and finally fires the optional outgoing webhook.
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest_asyncio
from sqlalchemy import select
from test_review_api_staged import _auth, _make_chain, _make_user

from app.api.routes import invitations as invitations_route
from app.config import settings
from app.db.models import (
    OrgInvitation,
    OrgMember,
    OrgMemberRepo,
    Repository,
    WatchedRepo,
)
from app.services import mail

API = settings.API_V1_PREFIX
_ORGS = f"{API}/orgs"
_INV = f"{API}/invitations"

_EMAIL = "grantee@example.com"
_INSTALLATION_A = 777601
_INSTALLATION_B = 777602


@pytest_asyncio.fixture
async def gstage(db):
    """Org A with TWO repositories + an ORG_ADMIN inviter; a foreign org B;
    and an invitee whose account email matches and who has a GitHub id
    (the collaborator pass needs one)."""
    a = await _make_chain(
        db,
        installation_id=_INSTALLATION_A,
        owner="owner-g",
        org_name="org-g",
        number=51,
    )
    b = await _make_chain(
        db,
        installation_id=_INSTALLATION_B,
        owner="owner-x",
        org_name="org-x",
        number=52,
    )
    second = Repository(
        installation_id=a.repo.installation_id,
        github_repo_id=_INSTALLATION_A + 1000,
        name="second",
        full_name="owner-g/second",
    )
    db.add(second)

    admin = await _make_user(db, "kc-grant-admin")
    invitee = await _make_user(db, "kc-grant-invitee")
    invitee.email = _EMAIL
    invitee.github_id = 99900111
    db.add(OrgMember(org_id=a.org.id, user_id=admin.id, role="ORG_ADMIN"))
    await db.commit()
    await db.refresh(second)

    return SimpleNamespace(
        a=a,
        b=b,
        second=second,
        admin=admin,
        invitee=invitee,
        h_admin=_auth("kc-grant-admin"),
        h_invitee=_auth("kc-grant-invitee"),
    )


def _capture_mail(monkeypatch) -> list[dict]:
    sent: list[dict] = []

    def fake_send(*, to, org_name, role, invite_url):
        sent.append({"to": to, "invite_url": invite_url})

    monkeypatch.setattr(mail, "send_invitation_email", fake_send)
    return sent


def _token_from(capture: dict) -> str:
    return parse_qs(urlparse(capture["invite_url"]).query)["token"][0]


async def _invite(client, stage, repo_ids=(), *, role="DEVELOPER", email=_EMAIL):
    return await client.post(
        f"{_ORGS}/{stage.a.org.id}/invitations",
        json={
            "email": email,
            "role": role,
            "repository_ids": [str(rid) for rid in repo_ids],
        },
        headers=stage.h_admin,
    )


# --- create ------------------------------------------------------------------


async def test_create_stores_and_echoes_selected_repositories(client, db, gstage):
    resp = await _invite(client, gstage, [gstage.a.repo.id, gstage.second.id])
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["repository_ids"] == [
        str(gstage.a.repo.id),
        str(gstage.second.id),
    ]
    assert body["repositories"] == ["owner-g/demo", "owner-g/second"]
    assert body["github_error"] is None

    row = (
        await db.execute(select(OrgInvitation).where(OrgInvitation.id == body["id"]))
    ).scalar_one()
    assert [str(rid) for rid in row.repository_ids] == [
        str(gstage.a.repo.id),
        str(gstage.second.id),
    ]


async def test_create_dedupes_duplicate_repository_ids(client, gstage):
    resp = await _invite(
        client, gstage, [gstage.a.repo.id, gstage.a.repo.id, gstage.a.repo.id]
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["repository_ids"] == [str(gstage.a.repo.id)]


async def test_create_rejects_foreign_repository_before_any_write(client, db, gstage):
    # org B's repository is not part of org A's installation.
    resp = await _invite(client, gstage, [gstage.b.repo.id])
    assert resp.status_code == 400
    assert "Unknown repositories" in resp.json()["detail"]

    # …and a totally unknown UUID behaves the same (no enumeration).
    resp = await _invite(client, gstage, ["00000000-0000-0000-0000-000000000001"])
    assert resp.status_code == 400

    assert (await db.execute(select(OrgInvitation))).scalars().all() == []


async def test_create_caps_the_repository_selection(client, gstage):
    uuids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(101)]
    resp = await client.post(
        f"{_ORGS}/{gstage.a.org.id}/invitations",
        json={"email": _EMAIL, "role": "DEVELOPER", "repository_ids": uuids},
        headers=gstage.h_admin,
    )
    assert resp.status_code == 422


# --- preview / list ----------------------------------------------------------


async def test_preview_and_list_carry_repository_names(client, gstage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage, [gstage.a.repo.id, gstage.second.id])
    token = _token_from(sent[0])

    preview = (await client.get(f"{_INV}/{token}")).json()
    assert preview["repositories"] == ["owner-g/demo", "owner-g/second"]
    # The public preview never carries ids (no enumeration from a token).
    assert "repository_ids" not in preview

    items = (
        await client.get(
            f"{_ORGS}/{gstage.a.org.id}/invitations", headers=gstage.h_admin
        )
    ).json()
    assert items[0]["repositories"] == ["owner-g/demo", "owner-g/second"]
    assert items[0]["repository_ids"] == [
        str(gstage.a.repo.id),
        str(gstage.second.id),
    ]


# --- accept ------------------------------------------------------------------


async def _fake_token(installation_id: int) -> str:
    """Stand-in for ``get_installation_token`` (must be awaitable)."""
    return f"ghs_{installation_id}_token"


async def test_accept_grants_repos_and_adds_github_collaborators(
    client, db, gstage, monkeypatch
):
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage, [gstage.a.repo.id, gstage.second.id], role="REVIEWER")
    token = _token_from(sent[0])

    calls: list[dict] = []

    async def fake_ensure(*, installation_token, full_name, username, permission):
        calls.append(
            {
                "installation_token": installation_token,
                "full_name": full_name,
                "username": username,
                "permission": permission,
            }
        )
        return True, None

    monkeypatch.setattr(invitations_route, "get_installation_token", _fake_token)
    monkeypatch.setattr(invitations_route, "ensure_collaborator", fake_ensure)

    resp = await client.post(f"{_INV}/{token}/accept", headers=gstage.h_invitee)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "REVIEWER"
    assert body["github_error"] is None  # both collaborator adds succeeded

    # Membership + per-repo grants + watched (review) rows, all persisted.
    grants = (
        (
            await db.execute(
                select(OrgMemberRepo)
                .where(OrgMemberRepo.user_id == gstage.invitee.id)
                .order_by(OrgMemberRepo.repo_id)
            )
        )
        .scalars()
        .all()
    )
    assert {g.repo_id for g in grants} == {gstage.a.repo.id, gstage.second.id}
    assert {g.role for g in grants} == {"REVIEWER"}
    assert all(g.github_collaborator for g in grants)
    assert all(g.github_error is None for g in grants)

    watched = (
        (
            await db.execute(
                select(WatchedRepo).where(WatchedRepo.user_id == gstage.invitee.id)
            )
        )
        .scalars()
        .all()
    )
    assert {w.repo_id for w in watched} == {
        gstage.a.repo.github_repo_id,
        gstage.second.github_repo_id,
    }

    # One GitHub call per repository, with the role's permission and the
    # organization's installation token (never a user OAuth token).
    assert {c["full_name"] for c in calls} == {"owner-g/demo", "owner-g/second"}
    assert {c["permission"] for c in calls} == {"triage"}
    assert {c["username"] for c in calls} == {"kc-grant-invitee"}
    assert {c["installation_token"] for c in calls} == {f"ghs_{_INSTALLATION_A}_token"}


async def test_accept_never_fails_when_github_says_no(client, db, gstage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage, [gstage.a.repo.id])
    token = _token_from(sent[0])

    async def fake_ensure(**kwargs):
        return False, "HTTP 403 Resource not accessible"

    monkeypatch.setattr(invitations_route, "get_installation_token", _fake_token)
    monkeypatch.setattr(invitations_route, "ensure_collaborator", fake_ensure)

    resp = await client.post(f"{_INV}/{token}/accept", headers=gstage.h_invitee)
    assert resp.status_code == 200  # the accept itself still succeeded
    body = resp.json()
    assert "owner-g/demo" in body["github_error"]
    assert "HTTP 403" in body["github_error"]

    # The failure is stored per repo and joined onto the invitation row.
    grant = (
        await db.execute(
            select(OrgMemberRepo).where(OrgMemberRepo.user_id == gstage.invitee.id)
        )
    ).scalar_one()
    assert grant.github_collaborator is False
    assert "HTTP 403" in grant.github_error

    invitation = (
        await db.execute(select(OrgInvitation).where(OrgInvitation.email == _EMAIL))
    ).scalar_one()
    assert invitation.status == "accepted"
    assert "owner-g/demo" in invitation.github_error

    # The org membership is untouched by the GitHub failure.
    member = (
        await db.execute(
            select(OrgMember).where(OrgMember.user_id == gstage.invitee.id)
        )
    ).scalar_one()
    assert member.role == "DEVELOPER"


async def test_accept_records_missing_github_identity(client, db, gstage, monkeypatch):
    """An invitee without a linked GitHub account can still join — the
    grant rows stay, only the collaborator flag records why it failed."""
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage, [gstage.a.repo.id])
    token = _token_from(sent[0])

    token_calls: list = []

    async def guard_token(*args, **kwargs):  # pragma: no cover - guarded
        token_calls.append(args)
        raise AssertionError("no token should be minted without an identity")

    monkeypatch.setattr(invitations_route, "get_installation_token", guard_token)
    gstage.invitee.github_id = None
    await db.commit()

    resp = await client.post(f"{_INV}/{token}/accept", headers=gstage.h_invitee)
    assert resp.status_code == 200
    assert "no GitHub account linked" in resp.json()["github_error"]
    assert token_calls == []  # identity was checked BEFORE minting a token

    grant = (
        await db.execute(
            select(OrgMemberRepo).where(OrgMemberRepo.user_id == gstage.invitee.id)
        )
    ).scalar_one()
    assert grant.github_collaborator is False
    assert "no GitHub account linked" in grant.github_error


async def test_org_only_invitation_skips_the_github_pass(
    client, db, gstage, monkeypatch
):
    """No repository_ids → no collaborator calls at all."""
    token_calls: list = []

    async def guard_token(*args, **kwargs):  # pragma: no cover - guarded
        token_calls.append(args)
        raise AssertionError("no GitHub call for an org-only invitation")

    monkeypatch.setattr(invitations_route, "get_installation_token", guard_token)

    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage)  # no repositories
    token = _token_from(sent[0])

    resp = await client.post(f"{_INV}/{token}/accept", headers=gstage.h_invitee)
    assert resp.status_code == 200
    assert resp.json()["github_error"] is None
    assert token_calls == []
    assert (await db.execute(select(OrgMemberRepo))).scalars().all() == []


# --- outgoing webhook --------------------------------------------------------


async def test_webhook_fires_after_a_successful_accept(client, gstage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage, [gstage.a.repo.id])
    token = _token_from(sent[0])

    posts: list[tuple[str, dict]] = []

    async def fake_post(url, payload):
        posts.append((url, payload))

    monkeypatch.setattr(invitations_route, "_post_json", fake_post)
    monkeypatch.setattr(
        settings, "INVITATION_WEBHOOK_URL", "https://consumer.example/invites"
    )
    monkeypatch.setattr(invitations_route, "get_installation_token", _fake_token)

    async def fake_ensure(**kwargs):
        return True, None

    monkeypatch.setattr(invitations_route, "ensure_collaborator", fake_ensure)

    resp = await client.post(f"{_INV}/{token}/accept", headers=gstage.h_invitee)
    assert resp.status_code == 200

    assert len(posts) == 1
    url, payload = posts[0]
    assert url == "https://consumer.example/invites"
    assert payload["event"] == "org_invitation.accepted"
    assert payload["org_name"] == "org-g"
    assert payload["invitee"]["login"] == "kc-grant-invitee"
    assert payload["role"] == "DEVELOPER"
    assert payload["github_error"] is None
    assert payload["repositories"] == [
        {
            "id": str(gstage.a.repo.id),
            "github_repo_id": gstage.a.repo.github_repo_id,
            "full_name": "owner-g/demo",
            "role": "DEVELOPER",
            "github_collaborator": True,
        }
    ]
    assert payload["invitation_id"]
    assert payload["accepted_at"]


async def test_webhook_is_skipped_when_not_configured(client, gstage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage)
    token = _token_from(sent[0])

    posted: list = []

    async def record(url, payload):  # pragma: no cover - guarded
        posted.append(url)

    monkeypatch.setattr(invitations_route, "_post_json", record)

    resp = await client.post(f"{_INV}/{token}/accept", headers=gstage.h_invitee)
    assert resp.status_code == 200
    assert posted == []  # INVITATION_WEBHOOK_URL defaults to empty


async def test_webhook_failure_never_fails_the_accept(client, gstage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage)
    token = _token_from(sent[0])

    async def boom(url, payload):  # pragma: no cover - exercised
        raise RuntimeError("consumer is down")

    monkeypatch.setattr(invitations_route, "_post_json", boom)
    monkeypatch.setattr(
        settings, "INVITATION_WEBHOOK_URL", "https://consumer.example/invites"
    )

    resp = await client.post(f"{_INV}/{token}/accept", headers=gstage.h_invitee)
    assert resp.status_code == 200


# --- hash/token hygiene ------------------------------------------------------


async def test_repo_grant_flow_never_leaks_the_raw_token(client, gstage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _invite(client, gstage, [gstage.a.repo.id])
    token = _token_from(sent[0])

    created = await client.get(
        f"{_ORGS}/{gstage.a.org.id}/invitations", headers=gstage.h_admin
    )
    preview = await client.get(f"{_INV}/{token}")

    assert token not in created.text
    assert token not in preview.text
    assert "token_hash" not in created.text
    assert "token_hash" not in preview.text
