"""GET /api/v1/auth/keycloak/config (public SPA bootstrap)."""

from app.config import settings

API = settings.API_V1_PREFIX


async def test_keycloak_config_is_public_and_shape(client):
    """No auth header needed; returns url/realm/clientId for keycloak-js."""
    resp = await client.get(f"{API}/auth/keycloak/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["realm"] == "codesage-realm"
    assert body["clientId"] == "codesage-angular"
    assert body["url"].startswith("http")
    # Browser URL comes from FRONTEND_URL (+/auth fallback), never the
    # in-cluster service hostname.
    assert "keycloak-service" not in body["url"]
    assert body["url"].endswith("/auth")


async def test_me_still_requires_token(client):
    """The config endpoint being public must not leak into /auth/me."""
    resp = await client.get(f"{API}/auth/me")
    assert resp.status_code == 401
