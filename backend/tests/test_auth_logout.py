"""POST /api/v1/auth/logout: OAuth-row purge, iat-cutoff revocation."""

import time

from conftest import make_keycloak_token
from sqlalchemy import func, select

from app.config import settings
from app.db.models import OAuthToken
from app.redis import REVOKED_AT_KEY, get_redis

API = settings.API_V1_PREFIX


async def test_logout_deletes_oauth_token_rows(client, user, db):
    """Logout really deletes oauth_tokens rows and keeps the shape."""
    db.add(
        OAuthToken(user_id=user.id, access_token="gho_test", refresh_token="ghr_test")
    )
    await db.commit()

    token = make_keycloak_token(sub="kc-sub-test-user")
    resp = await client.post(
        f"{API}/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"message": "Logged out successfully"}

    token_count = (
        await db.execute(
            select(func.count())
            .select_from(OAuthToken)
            .where(OAuthToken.user_id == user.id)
        )
    ).scalar_one()
    assert token_count == 0


async def test_logout_revokes_older_access_but_not_newer(client, user):
    """iat < cutoff → 401; a token minted after the cutoff (iat > cutoff) → 200."""
    pre_logout_access = make_keycloak_token(
        sub="kc-sub-test-user", iat=int(time.time()) - 60
    )

    logout = await client.post(
        f"{API}/auth/logout",
        headers={
            "Authorization": f"Bearer {make_keycloak_token(sub='kc-sub-test-user')}"
        },
    )
    assert logout.status_code == 200

    stale = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {pre_logout_access}"}
    )
    assert stale.status_code == 401

    cutoff = float(await get_redis().get(REVOKED_AT_KEY.format(user_id=user.id)))
    post_logout_access = make_keycloak_token(
        sub="kc-sub-test-user", iat=int(cutoff) + 10
    )
    accepted = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {post_logout_access}"}
    )
    assert accepted.status_code == 200
    assert accepted.json()["id"] == str(user.id)


async def test_logout_without_valid_identity_rejected(client):
    """Garbage Bearer or no credentials at all → 401."""
    garbage = await client.post(
        f"{API}/auth/logout", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert garbage.status_code == 401

    bare = await client.post(f"{API}/auth/logout")
    assert bare.status_code == 401
