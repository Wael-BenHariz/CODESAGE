"""Token-hardening contract (feature/auth-hardening).

1. ``typ`` enforcement: only ``typ == "Bearer"`` access tokens are accepted —
   ID tokens and refresh tokens are rejected even when signature, issuer,
   audience and expiry are all valid.
2. Role-claim rejection: a token with NEITHER ``realm_access`` NOR a flat
   ``roles`` claim is a 401, never the fallback role.
3. Fallback role: ``realm_access`` present but no recognized role name
   (e.g. only ``default-roles-*``) → GUEST for non-GitHub tokens
   (fail-closed), but DEVELOPER when the token carries the GitHub identity
   claims (``githubId``/``githubLogin`` — a GitHub-brokered session), with an
   explicit GUEST/SUPER_ADMIN still outranking that fallback — identically in
   ``app.security.roles.derive_role`` and the frontend ``deriveRole``.
4. The generic 401 body never leaks which check failed.
"""

from conftest import make_keycloak_token

from app.config import settings

API = settings.API_V1_PREFIX

_GENERIC_401 = "Invalid or expired token"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _me(client, token: str):
    """GET /auth/me with the token — the single choke point for all checks."""
    return await client.get(f"{API}/auth/me", headers=_auth(token))


# --- 1. typ enforcement -----------------------------------------------------


async def test_id_token_as_bearer_rejected(client):
    """A perfect ID token (typ "ID") replayed as a Bearer token → 401.

    It passes signature/issuer/expiry and even the azp check (ID tokens are
    minted for the SPA client) — only ``typ`` stands between it and
    acceptance, so the response must still be the generic body.
    """
    token = make_keycloak_token(typ="ID", roles=("DEVELOPER",))
    resp = await _me(client, token)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401
    # The type check, not a side-effect, must be what rejected it:
    assert "typ" not in resp.text and "ID token" not in resp.text


async def test_refresh_token_as_bearer_rejected(client):
    """A refresh token (typ "Refresh") → 401, generic body."""
    token = make_keycloak_token(typ="Refresh", roles=("DEVELOPER",))
    resp = await _me(client, token)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401


async def test_valid_bearer_typ_still_accepted(client, user):
    """Control: the same token with the default typ passes untouched."""
    token = make_keycloak_token(roles=("DEVELOPER",))
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "DEVELOPER"


# --- 2. role-claim rejection ------------------------------------------------


async def test_access_token_without_role_claim_rejected(client):
    """No realm_access and no flat roles → 401 (not fallback DEVELOPER/GUEST).

    The token is otherwise valid (correct typ, azp, issuer, expiry), so this
    pins rejection on the missing role claim alone.
    """
    token = make_keycloak_token(roles=None)
    resp = await _me(client, token)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401


async def test_access_token_with_flat_roles_claim_accepted(client):
    """Flat top-level ``roles`` counts as a role source (fallback setup).

    Built by hand because ``make_keycloak_token``'s ``roles`` kwarg always
    writes ``realm_access`` — this token must have ONLY the flat claim.
    """
    import time as _time

    from conftest import _KC_KID, _KC_PRIVATE_PEM
    from jose import jwt as jose_jwt

    now = int(_time.time())
    payload = {
        "sub": "kc-sub-flat",
        "iss": settings.KEYCLOAK_ISSUER,
        "azp": "codesage-angular",
        "typ": "Bearer",
        "iat": now,
        "exp": now + 300,
        "preferred_username": "flat-roles-user",
        "roles": ["DEVELOPER"],
    }
    token = jose_jwt.encode(
        payload, _KC_PRIVATE_PEM, algorithm="RS256", headers={"kid": _KC_KID}
    )
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "DEVELOPER"


# --- 3. fallback role (GUEST fail-closed; DEVELOPER via GitHub claims) ------


async def test_default_roles_only_falls_back_to_guest(client):
    """realm_access with only realm defaults (no GitHub claims) → GUEST."""
    token = make_keycloak_token(
        sub="kc-sub-defaults",
        roles=("default-roles-codesage-realm", "offline_access", "uma_authorization"),
    )
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "GUEST"


async def test_unrecognized_role_names_fall_back_to_guest(client):
    """Realm roles that aren't one of the three → GUEST (fail-closed)."""
    token = make_keycloak_token(sub="kc-sub-unknown", roles=("some-other-role",))
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "GUEST"


async def test_github_session_default_roles_falls_back_to_developer(client):
    """GitHub-brokered token (githubId claim) with only default realm roles
    → DEVELOPER: signing in through GitHub is the grant, no Keycloak role
    assignment needed."""
    token = make_keycloak_token(
        sub="kc-sub-github-defaults",
        roles=("default-roles-codesage-realm", "offline_access", "uma_authorization"),
        githubId=75458407,
        githubLogin="Wael-BenHariz",
    )
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "DEVELOPER"


async def test_github_login_claim_alone_is_enough(client):
    """githubLogin without githubId still counts as a GitHub session."""
    token = make_keycloak_token(
        sub="kc-sub-github-login-only",
        roles=("default-roles-codesage-realm",),
        githubLogin="some-login",
    )
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "DEVELOPER"


async def test_explicit_guest_downgrade_still_beats_github_fallback(client):
    """An explicit GUEST assignment outranks the GitHub-developer fallback —
    admins keep their read-only downgrade lever."""
    token = make_keycloak_token(
        sub="kc-sub-github-guest",
        roles=("default-roles-codesage-realm", "GUEST"),
        githubId=75458407,
    )
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "GUEST"


async def test_fallback_role_matches_backend_contract():
    """derive_role's fallback: GUEST by default, DEVELOPER for GitHub
    sessions — the guard the frontend mirrors."""
    from app.security.roles import derive_role

    # Non-GitHub session (fail-closed GUEST).
    assert derive_role([]) == "GUEST"
    assert derive_role(["default-roles-codesage-realm"]) == "GUEST"
    # GitHub-brokered session → DEVELOPER fallback.
    assert derive_role([], via_github=True) == "DEVELOPER"
    assert derive_role(["default-roles-codesage-realm"], via_github=True) == "DEVELOPER"
    # Explicit roles always outrank the GitHub fallback.
    assert derive_role(["GUEST"], via_github=True) == "GUEST"
    assert derive_role(["SUPER_ADMIN"], via_github=True) == "SUPER_ADMIN"


# --- 4. recognized roles unchanged ------------------------------------------


async def test_super_admin_token_unchanged(client):
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("SUPER_ADMIN",))
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "SUPER_ADMIN"


async def test_developer_token_unchanged(client):
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("DEVELOPER",))
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "DEVELOPER"


async def test_guest_token_unchanged(client):
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("GUEST",))
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "GUEST"


async def test_guest_outranks_developer_still(client):
    """Precedence SUPER_ADMIN > GUEST > DEVELOPER is untouched by the change."""
    token = make_keycloak_token(sub="kc-sub-test-user", roles=("DEVELOPER", "GUEST"))
    resp = await _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["role"] == "GUEST"


# --- 5. existing rejection paths, re-pinned with typ present ----------------


async def test_expired_token_rejected(client):
    token = make_keycloak_token(iat=-600, exp_in=60)  # expired 540s ago
    resp = await _me(client, token)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401


async def test_wrong_azp_rejected(client):
    """azp of another client (even with typ Bearer and valid roles) → 401."""
    token = make_keycloak_token(azp="some-other-client", roles=("DEVELOPER",))
    resp = await _me(client, token)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401


async def test_bad_signature_rejected(client):
    """Correct claims (incl. typ) signed with a key outside the JWKS → 401."""
    import time as _time

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt as jose_jwt

    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rogue_pem = rogue_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    now = int(_time.time())
    rogue = jose_jwt.encode(
        {
            "sub": "kc-sub-test-user",
            "iss": settings.KEYCLOAK_ISSUER,
            "azp": "codesage-angular",
            "typ": "Bearer",
            "iat": now,
            "exp": now + 300,
            "realm_access": {"roles": ["SUPER_ADMIN"]},
        },
        rogue_pem,
        algorithm="RS256",
        headers={"kid": "test-realm-key-1"},
    )
    resp = await _me(client, rogue)
    assert resp.status_code == 401
    assert resp.json()["detail"] == _GENERIC_401
