"""Real Keycloak/API integration fixtures. Never imported by unit pytest."""

import json
import os
import httpx
import pytest


@pytest.fixture(scope="session")
def integration_users():
    raw = os.getenv("E2E_USERS_JSON")
    if not raw:
        pytest.skip("E2E_USERS_JSON is not configured")
    return json.loads(raw)


@pytest.fixture(scope="session")
def api_base():
    default_port = os.getenv("E2E_API_PORT", "8002")
    return (
        os.getenv("E2E_API_URL", f"http://127.0.0.1:{default_port}").rstrip("/")
        + "/api/v1"
    )


@pytest.fixture(scope="session")
def token_for(integration_users):
    def issue(role):
        user = integration_users.get(role)
        if not user:
            pytest.skip(f"No Keycloak account configured for {role}")
        kc = os.environ["KEYCLOAK_PUBLIC_URL"].rstrip("/")
        realm = os.getenv("KEYCLOAK_REALM", "codesage-realm")
        endpoint = f"{kc}/realms/{realm}/protocol/openid-connect/token"
        response = httpx.post(
            endpoint,
            data={
                "grant_type": "password",
                "client_id": os.getenv("E2E_KEYCLOAK_CLIENT_ID", "codesage-angular"),
                "username": user["username"],
                "password": user["password"],
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["access_token"]

    return issue


@pytest.fixture
def api(api_base):
    with httpx.Client(base_url=api_base, timeout=20) as client:
        yield client
