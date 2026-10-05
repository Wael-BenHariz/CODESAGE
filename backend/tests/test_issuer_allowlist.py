"""Issuer allow-list contract (KEYCLOAK_ALLOWED_ISSUERS).

- setting is an env JSON array (list[str])
- empty setting falls back to [KEYCLOAK_ISSUER] (behavior unchanged)
- iss is exact-string matched against the list AFTER signature verification
- config rejects any allowed issuer that does not end with
  /realms/<KEYCLOAK_REALM>
"""

import json

import pytest
from conftest import make_keycloak_token
from pydantic import ValidationError

from app.config import Settings, settings

API = settings.API_V1_PREFIX
REALM = settings.KEYCLOAK_REALM
DEFAULT_ISS = settings.KEYCLOAK_ISSUER  # http://localhost:4200/auth/realms/...
# A second, conforming issuer — e.g. the same realm reached through a
# different MetalLB IP during a migration cutover.
OTHER_ISS = f"http://10.171.24.202/auth/realms/{REALM}"

_GENERIC_401 = "Invalid or expired token"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _me(client, token: str):
    return await client.get(f"{API}/auth/me", headers=_auth(token))


# --- runtime allow-list enforcement (via /auth/me) --------------------------


async def test_issuer_in_allowlist_accepted(monkeypatch, client):
    """iss is listed → accepted (200)."""
    monkeypatch.setattr(settings, "KEYCLOAK_ALLOWED_ISSUERS", [DEFAULT_ISS])
    token = make_keycloak_token()  # iss = DEFAULT_ISS
    resp = await _me(client, token)
    assert resp.status_code == 200


async def test_issuer_not_in_allowlist_rejected(monkeypatch, client):
    """iss is NOT listed → 401 with the generic body, even with a valid sig."""
    monkeypatch.setattr(settings, "KEYCLOAK_ALLOWED_ISSUERS", [OTHER_ISS])
    token = make_keycloak_token()  # iss = DEFAULT_ISS, not listed
    resp = await _me(client, token)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401
    assert "allow-list" not in resp.text and "issuer" not in resp.text


async def test_empty_allowlist_falls_back_to_default_issuer(monkeypatch, client):
    """Empty/unset setting → only the derived default issuer is accepted."""
    monkeypatch.setattr(settings, "KEYCLOAK_ALLOWED_ISSUERS", [])

    default_token = make_keycloak_token()  # iss = DEFAULT_ISS
    resp = await _me(client, default_token)
    assert resp.status_code == 200

    other_token = make_keycloak_token(issuer=OTHER_ISS)
    resp = await _me(client, other_token)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401


async def test_two_issuers_both_accepted(monkeypatch, client):
    """Migration shape: old + new issuer in the list → both validate."""
    monkeypatch.setattr(settings, "KEYCLOAK_ALLOWED_ISSUERS", [DEFAULT_ISS, OTHER_ISS])

    token_a = make_keycloak_token()  # iss = DEFAULT_ISS
    assert (await _me(client, token_a)).status_code == 200

    token_b = make_keycloak_token(issuer=OTHER_ISS)
    assert (await _me(client, token_b)).status_code == 200


# --- config: env parsing + startup validation (requirements 1 and 3) --------


def test_setting_parses_as_env_json_array(monkeypatch):
    """The env var is a JSON array → list[str] on the settings object."""
    expected = [DEFAULT_ISS, OTHER_ISS]
    monkeypatch.setenv("KEYCLOAK_ALLOWED_ISSUERS", json.dumps(expected))
    loaded = Settings()
    assert loaded.KEYCLOAK_ALLOWED_ISSUERS == expected
    assert loaded.KEYCLOAK_EFFECTIVE_ISSUERS == expected


def test_empty_setting_resolves_to_default_issuer():
    """Effective list is never empty: [] falls back to [KEYCLOAK_ISSUER]."""
    loaded = Settings(KEYCLOAK_ALLOWED_ISSUERS=[])
    assert loaded.KEYCLOAK_EFFECTIVE_ISSUERS == [loaded.KEYCLOAK_ISSUER]


@pytest.mark.parametrize(
    "bad_issuer",
    [
        "http://keycloak.example/auth",  # no realm suffix at all
        "http://keycloak.example/auth/realms/other-realm",  # different realm
        "http://keycloak.example/auth/realms/codesage-realm/extra",  # wrong tail
    ],
    ids=["no-realm", "other-realm", "extra-suffix"],
)
def test_config_rejects_issuer_not_belonging_to_realm(monkeypatch, bad_issuer):
    """Requirement 3: an allowed issuer must end with /realms/<KEYCLOAK_REALM>."""
    monkeypatch.setenv("KEYCLOAK_ALLOWED_ISSUERS", json.dumps([bad_issuer]))
    with pytest.raises(ValidationError, match="must end with"):
        Settings()


def test_config_accepts_conforming_issuer_and_default(monkeypatch):
    """The happy path still constructs (validation is a guard, not a blocker)."""
    monkeypatch.setenv("KEYCLOAK_ALLOWED_ISSUERS", json.dumps([OTHER_ISS]))
    assert Settings().KEYCLOAK_ALLOWED_ISSUERS == [OTHER_ISS]
