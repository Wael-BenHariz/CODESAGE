"""Step 11 — org invitations (plan §3).

Contracts covered here:

- **Guard matrix per endpoint**: create = member + ≥ ORG_ADMIN with NO
  PLATFORM_ADMIN bypass (F2: mutations need membership); list/revoke also
  admit PLATFORM_ADMIN (plan line); DEVELOPER → 403; NONE → 403 first on
  writes; cross-org → the uniform 404. One cross-org case per endpoint.
- **Role cap**: only DEVELOPER/REVIEWER are invitable — ORG_ADMIN and
  PLATFORM_ADMIN → 422 (schema ``Literal`` mirrors the migration 017
  CHECK); malformed email → 422.
- **Token flow**: the raw token exists only in the emailed link — the DB
  stores its SHA-256 hash; ``GET /invitations/{token}`` (public) returns
  ``{org_name, role, email_masked}`` for a pending invite and ONE
  identical 404 for invalid/expired/revoked/used (no enumeration).
- **Accept**: authenticated (any role, NONE included); used → 409,
  expired or revoked → 410; single-use via conditional UPDATE; membership
  upsert never downgrades (ORG_ADMIN stays ORG_ADMIN; DEVELOPER →
  REVIEWER upgrades); email mismatch allowed + reported.
- **Rate limit**: 20 invites/hour/org → 429, keyed per org.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest_asyncio
from sqlalchemy import select, update
from test_review_api_staged import _auth, _make_chain, _make_user

from app.config import settings
from app.db.models import OrgInvitation, OrgMember
from app.services import invite_rate_limit, mail

API = settings.API_V1_PREFIX
_ORGS = f"{API}/orgs"
_INV = f"{API}/invitations"

_INVITEE_EMAIL = "john@example.com"


@pytest_asyncio.fixture
async def istage(db):
    """Two orgs: A (ORG_ADMIN + DEVELOPER + NONE members) and B (ORG_ADMIN
    of its own), a PLATFORM_ADMIN with no membership anywhere, and an
    invitee user whose account email matches the invitation address."""
    a = await _make_chain(
        db, installation_id=777501, owner="owner-a", org_name="org-a", number=41
    )
    b = await _make_chain(
        db, installation_id=777502, owner="owner-b", org_name="org-b", number=42
    )
    admin_a = await _make_user(db, "kc-inv-admin-a")
    dev_a = await _make_user(db, "kc-inv-dev-a")
    none_a = await _make_user(db, "kc-inv-none-a", role="NONE")
    pa = await _make_user(db, "kc-inv-pa", role="PLATFORM_ADMIN")
    admin_b = await _make_user(db, "kc-inv-admin-b")
    newbie = await _make_user(db, "kc-inv-newbie")
    newbie.email = _INVITEE_EMAIL

    db.add(OrgMember(org_id=a.org.id, user_id=admin_a.id, role="ORG_ADMIN"))
    db.add(OrgMember(org_id=a.org.id, user_id=dev_a.id, role="DEVELOPER"))
    db.add(OrgMember(org_id=a.org.id, user_id=none_a.id, role="DEVELOPER"))
    db.add(OrgMember(org_id=b.org.id, user_id=admin_b.id, role="ORG_ADMIN"))
    await db.commit()

    return SimpleNamespace(
        a=a,
        b=b,
        admin_a=admin_a,
        dev_a=dev_a,
        none_a=none_a,
        pa=pa,
        admin_b=admin_b,
        newbie=newbie,
        h_admin_a=_auth("kc-inv-admin-a"),
        h_dev_a=_auth("kc-inv-dev-a"),
        h_none_a=_auth("kc-inv-none-a", ("NONE",)),
        h_pa=_auth("kc-inv-pa", ("PLATFORM_ADMIN",)),
        h_admin_b=_auth("kc-inv-admin-b"),
        h_newbie=_auth("kc-inv-newbie"),
    )


def _capture_mail(monkeypatch) -> list[dict]:
    """Replace the mail seam; returns the captured ``send_invitation_email``
    kwargs (the ONLY place the raw invite link ever travels)."""
    sent: list[dict] = []

    def fake_send(*, to, org_name, role, invite_url):
        sent.append(
            {"to": to, "org_name": org_name, "role": role, "invite_url": invite_url}
        )

    monkeypatch.setattr(mail, "send_invitation_email", fake_send)
    return sent


def _token_from(capture: dict) -> str:
    return parse_qs(urlparse(capture["invite_url"]).query)["token"][0]


async def _create(
    client, stage, *, email=_INVITEE_EMAIL, role="DEVELOPER", headers=None
):
    return await client.post(
        f"{_ORGS}/{stage.a.org.id}/invitations",
        json={"email": email, "role": role},
        headers=stage.h_admin_a if headers is None else headers,
    )


# --- create ------------------------------------------------------------------


async def test_create_stores_hash_and_sends_link(client, db, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    resp = await _create(client, istage)

    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == _INVITEE_EMAIL
    assert body["role"] == "DEVELOPER"
    assert body["status"] == "pending"
    assert body["invited_by"] == "kc-inv-admin-a"
    assert body["expires_at"] and body["created_at"]
    # The response never carries token material.
    assert "token" not in resp.text
    assert "token_hash" not in resp.text

    # The raw token exists ONLY inside the emailed link.
    assert len(sent) == 1
    assert sent[0]["to"] == _INVITEE_EMAIL
    assert sent[0]["org_name"] == "org-a"
    assert sent[0]["invite_url"].startswith(settings.FRONTEND_URL)
    assert "/invite/accept?token=" in sent[0]["invite_url"]
    token = _token_from(sent[0])

    row = (
        await db.execute(select(OrgInvitation).where(OrgInvitation.id == body["id"]))
    ).scalar_one()
    assert row.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert token not in row.token_hash
    # 7-day window (plan: expires_at = now() + 7 days).
    remaining = row.expires_at - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)


async def test_create_role_cap_and_email_are_422(client, istage):
    for role in ("ORG_ADMIN", "PLATFORM_ADMIN"):
        resp = await _create(client, istage, role=role)
        assert resp.status_code == 422, role
    resp = await _create(client, istage, email="not-an-email")
    assert resp.status_code == 422


async def test_create_guard_matrix(client, db, istage):
    # DEVELOPER member → 403.
    resp = await _create(client, istage, headers=istage.h_dev_a)
    assert resp.status_code == 403
    # NONE → 403 first (write endpoint), despite the DEVELOPER membership.
    resp = await _create(client, istage, headers=istage.h_none_a)
    assert resp.status_code == 403
    # Cross-org ORG_ADMIN → the uniform 404.
    resp = await _create(client, istage, headers=istage.h_admin_b)
    assert resp.status_code == 404
    # PLATFORM_ADMIN without membership → 404 (F2: no bypass on mutations).
    resp = await _create(client, istage, headers=istage.h_pa)
    assert resp.status_code == 404

    assert (await db.execute(select(OrgInvitation))).scalars().all() == []


# --- list / revoke -----------------------------------------------------------


async def test_list_guards_and_never_leaks_token(client, istage, monkeypatch):
    _capture_mail(monkeypatch)
    await _create(client, istage)

    resp = await client.get(
        f"{_ORGS}/{istage.a.org.id}/invitations", headers=istage.h_dev_a
    )
    assert resp.status_code == 403
    resp = await client.get(
        f"{_ORGS}/{istage.a.org.id}/invitations", headers=istage.h_admin_b
    )
    assert resp.status_code == 404
    # PLATFORM_ADMIN may list (plan: "List + revoke: ORG_ADMIN … or
    # PLATFORM_ADMIN").
    resp = await client.get(
        f"{_ORGS}/{istage.a.org.id}/invitations", headers=istage.h_pa
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"{_ORGS}/{istage.a.org.id}/invitations", headers=istage.h_admin_a
    )
    assert resp.status_code == 200
    items = resp.json()
    assert [i["email"] for i in items] == [_INVITEE_EMAIL]
    assert items[0]["status"] == "pending"
    assert items[0]["invited_by"] == "kc-inv-admin-a"
    assert "token_hash" not in resp.text
    assert "token" not in resp.text


async def test_revoke_guards_and_idempotency(client, istage):
    created = (await _create(client, istage)).json()
    invite_id = created["id"]

    resp = await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{invite_id}",
        headers=istage.h_dev_a,
    )
    assert resp.status_code == 403
    # Cross-org: B's admin scoped to B's collection → same 404 as unknown id.
    resp = await client.delete(
        f"{_ORGS}/{istage.b.org.id}/invitations/{invite_id}",
        headers=istage.h_admin_b,
    )
    assert resp.status_code == 404
    # Cross-org: B's admin pointing at A's collection → 404 at the guard.
    resp = await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{invite_id}",
        headers=istage.h_admin_b,
    )
    assert resp.status_code == 404
    resp = await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/00000000-0000-0000-0000-000000000000",
        headers=istage.h_admin_a,
    )
    assert resp.status_code == 404

    resp = await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{invite_id}",
        headers=istage.h_admin_a,
    )
    assert resp.status_code == 204
    # Idempotent: revoking again is a no-op 204.
    resp = await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{invite_id}",
        headers=istage.h_admin_a,
    )
    assert resp.status_code == 204

    items = (
        await client.get(
            f"{_ORGS}/{istage.a.org.id}/invitations", headers=istage.h_admin_a
        )
    ).json()
    assert items[0]["status"] == "revoked"


async def test_platform_admin_may_revoke(client, istage):
    created = (await _create(client, istage)).json()
    resp = await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{created['id']}",
        headers=istage.h_pa,
    )
    assert resp.status_code == 204


# --- public preview ----------------------------------------------------------


async def test_preview_is_public_and_masks_email(client, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _create(client, istage)
    token = _token_from(sent[0])

    # No Authorization header — the invitee has no session yet.
    resp = await client.get(f"{_INV}/{token}")
    assert resp.status_code == 200
    assert resp.json() == {
        "org_name": "org-a",
        "role": "DEVELOPER",
        "email_masked": "jo***@example.com",
        # Org-only invitation (no repository_ids) → empty grant list.
        "repositories": [],
    }
    assert _INVITEE_EMAIL not in resp.text


async def test_preview_uniform_404_for_every_unusable_state(
    client, db, istage, monkeypatch
):
    sent = _capture_mail(monkeypatch)
    created = (await _create(client, istage)).json()
    token = _token_from(sent[0])

    # (a) unknown token.
    resp_bad = await client.get(f"{_INV}/definitely-not-a-real-token")
    # (b) expired: age the row past its window.
    await db.execute(
        update(OrgInvitation)
        .where(OrgInvitation.id == created["id"])
        .values(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    )
    await db.commit()
    resp_expired = await client.get(f"{_INV}/{token}")
    # (c) revoked: a second invitation, revoked.
    sent.clear()
    created2 = (await _create(client, istage, email="jane@example.com")).json()
    token2 = _token_from(sent[0])
    await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{created2['id']}",
        headers=istage.h_admin_a,
    )
    resp_revoked = await client.get(f"{_INV}/{token2}")

    responses = (resp_bad, resp_expired, resp_revoked)
    assert {r.status_code for r in responses} == {404}
    # Identical detail in every case — nothing enumerable.
    assert {r.json()["detail"] for r in responses} == {"Invitation not found"}


# --- accept ------------------------------------------------------------------


async def test_accept_creates_membership_and_is_single_use(
    client, db, istage, monkeypatch
):
    sent = _capture_mail(monkeypatch)
    await _create(client, istage)  # addressed like newbie's account email
    token = _token_from(sent[0])

    resp = await client.post(f"{_INV}/{token}/accept", headers=istage.h_newbie)
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_name"] == "org-a"
    assert body["role"] == "DEVELOPER"
    assert body["email_mismatch"] is False

    member = (
        await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == istage.a.org.id,
                OrgMember.user_id == istage.newbie.id,
            )
        )
    ).scalar_one()
    assert member.role == "DEVELOPER"

    # Single-use: a replay/double-click → 409 …
    resp = await client.post(f"{_INV}/{token}/accept", headers=istage.h_newbie)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Invitation already used"
    # …and the preview for the used token joins the uniform 404.
    resp = await client.get(f"{_INV}/{token}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Invitation not found"


async def test_accept_requires_authentication(client, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _create(client, istage)
    token = _token_from(sent[0])
    resp = await client.post(f"{_INV}/{token}/accept")
    assert resp.status_code == 401


async def test_accept_allowed_for_none_role_user(client, db, istage, monkeypatch):
    """Any authenticated role may accept — NONE included (plan Step 11)."""
    sent = _capture_mail(monkeypatch)
    await _create(client, istage)
    token = _token_from(sent[0])
    joiner = await _make_user(db, "kc-inv-none-joiner", role="NONE")

    resp = await client.post(
        f"{_INV}/{token}/accept", headers=_auth("kc-inv-none-joiner", ("NONE",))
    )
    assert resp.status_code == 200

    member = (
        await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == istage.a.org.id,
                OrgMember.user_id == joiner.id,
            )
        )
    ).scalar_one()
    assert member.role == "DEVELOPER"


async def test_accept_expired_410_and_persists_expiry(client, db, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    created = (await _create(client, istage)).json()
    token = _token_from(sent[0])
    await db.execute(
        update(OrgInvitation)
        .where(OrgInvitation.id == created["id"])
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    )
    await db.commit()

    resp = await client.post(f"{_INV}/{token}/accept", headers=istage.h_newbie)
    assert resp.status_code == 410

    row = (
        await db.execute(select(OrgInvitation).where(OrgInvitation.id == created["id"]))
    ).scalar_one()
    assert row.status == "expired"  # expiry persisted on first sight
    member = (
        await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == istage.a.org.id,
                OrgMember.user_id == istage.newbie.id,
            )
        )
    ).scalar_one_or_none()
    assert member is None


async def test_accept_revoked_410(client, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    created = (await _create(client, istage)).json()
    token = _token_from(sent[0])
    await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{created['id']}",
        headers=istage.h_admin_a,
    )

    resp = await client.post(f"{_INV}/{token}/accept", headers=istage.h_newbie)
    assert resp.status_code == 410


async def test_revoke_after_accept_409(client, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    created = (await _create(client, istage)).json()
    token = _token_from(sent[0])
    accept = await client.post(f"{_INV}/{token}/accept", headers=istage.h_newbie)
    assert accept.status_code == 200

    resp = await client.delete(
        f"{_ORGS}/{istage.a.org.id}/invitations/{created['id']}",
        headers=istage.h_admin_a,
    )
    assert resp.status_code == 409
    # The membership survives — revocation never removes an accepted grant.
    assert accept.json()["role"] == "DEVELOPER"


async def test_accept_never_downgrades_membership(client, db, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    # ORG_ADMIN accepts a DEVELOPER invitation → stays ORG_ADMIN.
    await _create(client, istage, role="DEVELOPER", email="admin-a@example.com")
    token = _token_from(sent[0])
    resp = await client.post(f"{_INV}/{token}/accept", headers=istage.h_admin_a)
    assert resp.status_code == 200
    assert resp.json()["role"] == "ORG_ADMIN"
    member = (
        await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == istage.a.org.id,
                OrgMember.user_id == istage.admin_a.id,
            )
        )
    ).scalar_one()
    assert member.role == "ORG_ADMIN"

    # DEVELOPER accepts a REVIEWER invitation → upgraded (GREATEST-ish).
    sent.clear()
    await _create(client, istage, role="REVIEWER", email="dev-a@example.com")
    token2 = _token_from(sent[0])
    resp = await client.post(f"{_INV}/{token2}/accept", headers=istage.h_dev_a)
    assert resp.status_code == 200
    assert resp.json()["role"] == "REVIEWER"


async def test_accept_reports_email_mismatch(client, db, istage, monkeypatch):
    sent = _capture_mail(monkeypatch)
    await _create(client, istage, email="someone-else@example.com")
    token = _token_from(sent[0])

    resp = await client.post(f"{_INV}/{token}/accept", headers=istage.h_newbie)
    assert resp.status_code == 200
    assert resp.json()["email_mismatch"] is True
    # Mismatch is allowed — the membership exists anyway.
    member = (
        await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == istage.a.org.id,
                OrgMember.user_id == istage.newbie.id,
            )
        )
    ).scalar_one_or_none()
    assert member is not None


# --- rate limit --------------------------------------------------------------


async def test_rate_limit_is_per_org_and_returns_429(client, istage, monkeypatch):
    monkeypatch.setattr(invite_rate_limit, "INVITE_LIMIT_PER_HOUR", 2)

    assert (await _create(client, istage, email="one@example.com")).status_code == 201
    assert (await _create(client, istage, email="two@example.com")).status_code == 201
    limited = await _create(client, istage, email="three@example.com")
    assert limited.status_code == 429
    assert "rate limit" in limited.json()["detail"].lower()

    # A different org still has its own budget (the key includes org_id).
    resp = await client.post(
        f"{_ORGS}/{istage.b.org.id}/invitations",
        json={"email": "b@example.com", "role": "DEVELOPER"},
        headers=istage.h_admin_b,
    )
    assert resp.status_code == 201
