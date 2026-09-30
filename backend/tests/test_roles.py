"""Role guards (require_developer / require_super_admin) over the route table."""

from conftest import make_keycloak_token

from app.config import settings

API = settings.API_V1_PREFIX


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_guest_blocked_from_mutations(client):
    """GUEST reads fine, writes 403 with a generic detail."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("GUEST",))

    read = await client.get(f"{API}/github/status", headers=_auth(token))
    assert read.status_code == 200

    write = await client.put(
        f"{API}/settings/llm",
        json={"provider": "groq", "model": "x"},
        headers=_auth(token),
    )
    assert write.status_code == 403
    assert write.json()["detail"] == "Insufficient permissions"


async def test_developer_allowed_on_mutations(client, user):
    """DEVELOPER passes the guard (PUT reaches handler validation, not 403)."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("DEVELOPER",))

    write = await client.put(
        f"{API}/settings/llm",
        json={
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "api_key": "gsk_test_key",
        },
        headers=_auth(token),
    )
    assert write.status_code == 200


async def test_developer_blocked_from_user_admin(client):
    """GET /users (admin list) is SUPER_ADMIN-only."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("DEVELOPER",))

    resp = await client.get(f"{API}/users", headers=_auth(token))
    assert resp.status_code == 403


async def test_super_admin_allowed_on_user_admin(client, user):
    """SUPER_ADMIN lists users."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("SUPER_ADMIN",))

    resp = await client.get(f"{API}/users", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_guest_blocked_from_repo_selection(client):
    """POST /github/repos/selection requires DEVELOPER+."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("GUEST",))

    resp = await client.post(
        f"{API}/github/repos/selection", json={"repos": []}, headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_anonymous_gets_401_not_403_on_guarded_routes(client):
    """Guards still challenge unauthenticated callers with 401."""
    resp = await client.get(f"{API}/users")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
