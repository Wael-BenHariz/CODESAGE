"""Four-role model: derive_role contract + role guards over the route table.

Roles: PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER, plus the internal
read-only sentinel NONE (no ladder position). Legacy claims (SUPER_ADMIN,
GUEST) map through the one-release compat map. See
docs/PLAN_ROLES_SETTINGS_STAGED.md §2 and §6 (flag F1).
"""

import logging

import pytest
from conftest import make_keycloak_token
from fastapi import HTTPException

from app.config import settings
from app.db.models import User
from app.security.roles import (
    ROLE_DEVELOPER,
    ROLE_NONE,
    ROLE_ORG_ADMIN,
    ROLE_PLATFORM_ADMIN,
    ROLE_REVIEWER,
    derive_role,
    require_developer,
    require_reviewer,
    require_role,
    require_super_admin,
)

API = settings.API_V1_PREFIX

_ALL_FOUR = (ROLE_PLATFORM_ADMIN, ROLE_ORG_ADMIN, ROLE_REVIEWER, ROLE_DEVELOPER)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- derive_role: ladder + compat map ----------------------------------------


def test_every_role_derives_itself():
    for role in _ALL_FOUR:
        assert derive_role([role]) == role


def test_compat_map_legacy_claim_names():
    """SUPER_ADMIN -> PLATFORM_ADMIN, GUEST -> NONE (one-release compat)."""
    assert derive_role(["SUPER_ADMIN"]) == ROLE_PLATFORM_ADMIN
    assert derive_role(["GUEST"]) == ROLE_NONE


def test_legacy_guest_beats_developer():
    """Explicit legacy read-only downgrade outranks a DEVELOPER grant."""
    assert derive_role(["DEVELOPER", "GUEST"]) == ROLE_NONE


def test_platform_admin_beats_legacy_guest():
    """PLATFORM_ADMIN outranks the legacy GUEST downgrade (old
    SUPER_ADMIN > GUEST precedence preserved)."""
    assert derive_role(["SUPER_ADMIN", "GUEST"]) == ROLE_PLATFORM_ADMIN


def test_explicit_readonly_beats_new_roles():
    """NONE sits above ORG_ADMIN/REVIEWER — a GUEST claim always wins
    except against PLATFORM_ADMIN (fail-closed explicit downgrade)."""
    assert derive_role(["GUEST", "ORG_ADMIN"]) == ROLE_NONE
    assert derive_role(["GUEST", "REVIEWER"]) == ROLE_NONE


def test_ladder_without_legacy_claims():
    assert derive_role(["ORG_ADMIN", "DEVELOPER"]) == ROLE_ORG_ADMIN
    assert derive_role(["REVIEWER", "DEVELOPER"]) == ROLE_REVIEWER
    assert derive_role(["ORG_ADMIN", "REVIEWER"]) == ROLE_ORG_ADMIN
    assert derive_role(["PLATFORM_ADMIN", "ORG_ADMIN"]) == ROLE_PLATFORM_ADMIN


def test_unrecognized_claims_fail_closed_to_none():
    """Empty, realm-default and unknown claims derive NONE (never DEVELOPER)."""
    assert derive_role([]) == ROLE_NONE
    assert derive_role(["default-roles-codesage-realm"]) == ROLE_NONE
    assert derive_role(["some-other-role"]) == ROLE_NONE


def test_claim_matching_is_case_insensitive():
    assert derive_role(["platform_admin"]) == ROLE_PLATFORM_ADMIN


# --- derive_role: broker fallback (flag F1 — temporary, kept) -----------------


def test_broker_fallback_derives_developer_and_warns(caplog):
    """F1: a GitHub-brokered session with NO recognized or legacy claim keeps
    deriving DEVELOPER (pre-existing behavior), logging a structured warning
    (subject + derived role, no secrets) each time."""
    with caplog.at_level(logging.WARNING, logger="app.security.roles"):
        assert derive_role([], via_github=True, subject="user-42") == ROLE_DEVELOPER
        assert (
            derive_role(
                ["default-roles-codesage-realm"],
                via_github=True,
                subject="user-42",
            )
            == ROLE_DEVELOPER
        )

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 2, "each fallback use must log a warning"
    message = warnings[0].getMessage()
    assert "role_fallback_broker_developer" in message
    assert "user-42" in message
    assert "DEVELOPER" in message


def test_broker_fallback_never_overrides_any_claim(caplog):
    """F1 constraint: any recognized/legacy claim stops the fallback —
    a brokered GUEST stays NONE; claims always outrank the fallback."""
    with caplog.at_level(logging.WARNING, logger="app.security.roles"):
        assert derive_role(["GUEST"], via_github=True) == ROLE_NONE
        assert derive_role(["DEVELOPER"], via_github=True) == ROLE_DEVELOPER
        assert derive_role(["REVIEWER"], via_github=True) == ROLE_REVIEWER
        assert derive_role(["SUPER_ADMIN"], via_github=True) == ROLE_PLATFORM_ADMIN

    fallback_warnings = [r for r in caplog.records if "role_fallback" in r.getMessage()]
    assert fallback_warnings == [], "no fallback while any claim is present"


def test_non_brokered_session_never_falls_back(caplog):
    """Non-GitHub token with no role claim → NONE, and no fallback warning."""
    with caplog.at_level(logging.WARNING, logger="app.security.roles"):
        assert derive_role(["default-roles-codesage-realm"]) == ROLE_NONE
    assert [r for r in caplog.records if "role_fallback" in r.getMessage()] == []


# --- require_role factory -----------------------------------------------------


def test_require_role_rejects_unknown_and_empty():
    with pytest.raises(ValueError, match="Unknown role"):
        require_role("WIZARD")
    with pytest.raises(ValueError, match="at least one"):
        require_role()


# --- guard shorthands (called directly with a transient user row) -------------


def _user(role: str) -> User:
    return User(login=f"t-{role.lower()}", role=role)


async def test_require_developer_permits_every_real_role():
    for role in _ALL_FOUR:
        assert (await require_developer(current_user=_user(role))).role == role


async def test_require_developer_denies_none():
    """NONE is unconditionally read-only: 403, generic detail."""
    with pytest.raises(HTTPException) as exc:
        await require_developer(current_user=_user(ROLE_NONE))
    assert exc.value.status_code == 403
    assert exc.value.detail == "Insufficient permissions"


async def test_require_reviewer_permits_reviewer_and_above():
    for role in (ROLE_PLATFORM_ADMIN, ROLE_ORG_ADMIN, ROLE_REVIEWER):
        assert (await require_reviewer(current_user=_user(role))).role == role
    for role in (ROLE_DEVELOPER, ROLE_NONE):
        with pytest.raises(HTTPException) as exc:
            await require_reviewer(current_user=_user(role))
        assert exc.value.status_code == 403


async def test_require_super_admin_permits_only_platform_admin():
    assert (
        await require_super_admin(current_user=_user(ROLE_PLATFORM_ADMIN))
    ).role == (ROLE_PLATFORM_ADMIN)
    for role in (ROLE_ORG_ADMIN, ROLE_REVIEWER, ROLE_DEVELOPER, ROLE_NONE):
        with pytest.raises(HTTPException) as exc:
            await require_super_admin(current_user=_user(role))
        assert exc.value.status_code == 403


# --- guards over the route table (tokens) -------------------------------------


async def test_none_role_reads_but_cannot_write_any_endpoint(client, user):
    """NONE gets 403 on write endpoints — checked on more than one route,
    with both a legacy GUEST claim and a direct NONE claim."""
    for roles in (("GUEST",), ("NONE",)):
        token = make_keycloak_token(sub="kc-sub-test-user", roles=roles)

        read = await client.get(f"{API}/github/status", headers=_auth(token))
        assert read.status_code == 200

        write = await client.put(
            f"{API}/settings/llm",
            json={"provider": "groq", "model": "x"},
            headers=_auth(token),
        )
        assert write.status_code == 403
        assert write.json()["detail"] == "Insufficient permissions"

        selection = await client.post(
            f"{API}/github/repos/selection", json={"repos": []}, headers=_auth(token)
        )
        assert selection.status_code == 403


_LLM_SETTINGS_BODY = {
    "provider": "groq",
    "model": "openai/gpt-oss-120b",
    "api_key": "gsk_test_key",
}


async def test_developer_role_matrix(client, user):
    """DEVELOPER: writes allowed, /users (user admin) denied."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=(ROLE_DEVELOPER,))

    write = await client.put(
        f"{API}/settings/llm", json=_LLM_SETTINGS_BODY, headers=_auth(token)
    )
    assert write.status_code == 200

    admin = await client.get(f"{API}/users", headers=_auth(token))
    assert admin.status_code == 403


async def test_reviewer_role_matrix(client, user):
    """REVIEWER inherits DEVELOPER write access, not user admin."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=(ROLE_REVIEWER,))

    write = await client.put(
        f"{API}/settings/llm", json=_LLM_SETTINGS_BODY, headers=_auth(token)
    )
    assert write.status_code == 200

    admin = await client.get(f"{API}/users", headers=_auth(token))
    assert admin.status_code == 403


async def test_org_admin_role_matrix(client, user):
    """ORG_ADMIN inherits write access, not user admin (platform-only)."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=(ROLE_ORG_ADMIN,))

    write = await client.put(
        f"{API}/settings/llm", json=_LLM_SETTINGS_BODY, headers=_auth(token)
    )
    assert write.status_code == 200

    admin = await client.get(f"{API}/users", headers=_auth(token))
    assert admin.status_code == 403


async def test_platform_admin_role_matrix(client, user):
    """PLATFORM_ADMIN: writes allowed and lists users."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=(ROLE_PLATFORM_ADMIN,))

    write = await client.put(
        f"{API}/settings/llm", json=_LLM_SETTINGS_BODY, headers=_auth(token)
    )
    assert write.status_code == 200

    admin = await client.get(f"{API}/users", headers=_auth(token))
    assert admin.status_code == 200
    assert admin.json()["total"] >= 1


async def test_legacy_super_admin_claim_maps_to_platform_admin(client, user):
    """Compat: a SUPER_ADMIN token still passes the platform-admin guard."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("SUPER_ADMIN",))

    resp = await client.get(f"{API}/users", headers=_auth(token))
    assert resp.status_code == 200


async def test_anonymous_gets_401_not_403_on_guarded_routes(client):
    """Guards still challenge unauthenticated callers with 401."""
    resp = await client.get(f"{API}/users")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
