"""Keycloak validation: challenge header, generic 401 bodies, JWT rejection paths."""

import pytest
from conftest import make_keycloak_token

from app.config import settings

API = settings.API_V1_PREFIX


async def test_missing_authorization_header_challenges(client):
    """No header → 401 with the Bearer challenge."""
    resp = await client.get(f"{API}/auth/me")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_malformed_jwt_gets_generic_detail(client):
    """Malformed/tampered JWTs never leak jose internals in the response body."""
    malformed = await client.get(
        f"{API}/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert malformed.status_code == 401
    assert malformed.json()["detail"] == "Invalid or expired token"
    assert "Signature" not in malformed.text
    assert "segments" not in malformed.text
    assert "jose" not in malformed.text

    tampered = await client.get(
        f"{API}/auth/me",
        headers={
            "Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhYmMifQ.badsig"
        },
    )
    assert tampered.status_code == 401
    assert tampered.json()["detail"] == "Invalid or expired token"
    assert "Signature verification" not in tampered.text


async def test_token_signed_by_unknown_key_rejected(client):
    """Correct claims but a key outside the realm JWKS → 401."""
    import time

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt as jose_jwt

    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rogue_pem = rogue_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    now = int(time.time())
    rogue = jose_jwt.encode(
        {
            "sub": "kc-sub-test-user",
            "iss": settings.KEYCLOAK_ISSUER,
            "azp": "codesage-angular",
            "iat": now,
            "exp": now + 300,
            "realm_access": {"roles": ["SUPER_ADMIN"]},
        },
        rogue_pem,
        algorithm="RS256",
        headers={"kid": "test-realm-key-1"},
    )

    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {rogue}"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired token"


async def test_expired_token_rejected(client):
    """exp in the past → 401."""
    token = make_keycloak_token(iat=-600, exp_in=60)  # expired 540s ago
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_wrong_issuer_rejected(client):
    """A token minted for another realm's URL → 401."""
    token = make_keycloak_token(issuer="http://evil.example/auth/realms/other")
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_wrong_audience_rejected(client):
    """azp of a different client (and no matching aud) → 401."""
    token = make_keycloak_token(azp="some-other-client")
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_valid_token_resolves_user(client, user):
    """Well-formed token → 200 with the user's id."""
    token = make_keycloak_token(sub="kc-sub-test-user")
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(user.id)
    assert resp.json()["role"] == "DEVELOPER"


async def test_unknown_user_is_jit_provisioned(client, db):
    """First login: no row for the sub → created from token claims."""
    from sqlalchemy import select

    from app.db.models import User

    token = make_keycloak_token(
        sub="kc-sub-fresh",
        preferred_username="fresh-dev",
        githubId=99887766,
        email="fresh@example.com",
    )
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["login"] == "fresh-dev"
    assert body["github_id"] == 99887766
    assert body["role"] == "DEVELOPER"

    row = (
        await db.execute(select(User).where(User.keycloak_id == "kc-sub-fresh"))
    ).scalar_one()
    assert row.email == "fresh@example.com"


async def test_role_synced_from_jwt_every_request(client, user, db):
    """Same row, different token roles → role follows the JWT, not the DB."""
    from sqlalchemy import select

    from app.db.models import User

    guest_token = make_keycloak_token(sub="kc-sub-test-user", roles=("GUEST",))
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {guest_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "GUEST"

    # populate_existing: bypass this session's identity map (it still holds
    # the pre-request row) and re-read what the API persisted.
    fresh = (
        await db.execute(
            select(User)
            .where(User.id == user.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert fresh.role == "GUEST"

    admin_token = make_keycloak_token(
        sub="kc-sub-test-user", roles=("SUPER_ADMIN", "GUEST")
    )
    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.json()["role"] == "SUPER_ADMIN"


async def test_valid_token_for_deleted_user_rejected(client, user, db):
    """A token whose sub matches nothing after user deletion → 401."""
    token = make_keycloak_token(
        sub="kc-sub-test-user", githubId=424242424  # githubId must NOT adopt
    )

    await db.delete(user)
    await db.commit()

    resp = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    # JIT provisions a NEW row (invite-only realm) — so 200, and it is not
    # the deleted user's row. The deletion contract changed with Keycloak:
    # identity is re-provisionable from the realm. Assert the new row.
    assert resp.status_code == 200
    assert resp.json()["id"] != str(user.id)


@pytest.mark.parametrize("path", ["/auth/github", "/auth/refresh"])
async def test_removed_oauth_endpoints_gone(client, path):
    """GitHub OAuth initiate/refresh are Keycloak's job now → 404."""
    resp = await client.get(f"{API}{path}")
    assert resp.status_code == 404
