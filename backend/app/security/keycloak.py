"""Keycloak RS256 JWT validation (JWKS-based).

Replaces the old HS256 ``token_manager`` decode path: tokens are minted by
Keycloak, the backend only validates them — signature against the realm's
published JWKS, issuer, audience, and expiry. The HS256 ``SECRET_KEY`` is
never used to sign or verify access tokens anymore.
"""

import logging
import time
from typing import Any

import httpx
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)


_jwks_cache: dict[str, Any] = {"fetched_at": 0.0, "keys": None}


def _now() -> float:
    return time.time()


def _stale() -> bool:
    ttl = settings.KEYCLOAK_JWKS_CACHE_TTL
    fetched_at = _jwks_cache["fetched_at"]
    return _jwks_cache["keys"] is None or (_now() - float(fetched_at)) > ttl


async def _fetch_jwks() -> dict[str, Any]:
    """Fetch (or refetch) the realm JWKS document, blocking on nothing."""
    uri = settings.KEYCLOAK_JWKS_URI
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(uri)
        resp.raise_for_status()
        doc = resp.json()
    _jwks_cache["keys"] = doc
    _jwks_cache["fetched_at"] = _now()
    logger.debug("JWKS refetched from %s (%d keys)", uri, len(doc.get("keys", [])))
    return doc


async def _get_jwks(force: bool = False) -> dict[str, Any]:
    if force or _stale():
        try:
            return await _fetch_jwks()
        except (httpx.HTTPError, ValueError) as exc:
            # Stale-but-present keys are better than a hard auth outage.
            if _jwks_cache["keys"] is not None:
                logger.warning("JWKS refresh failed, serving cached document: %s", exc)
                return _jwks_cache["keys"]
            raise
    return _jwks_cache["keys"]


def _kid_from_token(token: str) -> str | None:
    try:
        headers = jwt.get_unverified_header(token)
    except JWTError:
        return None
    kid = headers.get("kid")
    return str(kid) if kid else None


def _select_key(jwks: dict[str, Any], token: str) -> dict[str, Any]:
    """Pick the JWKS entry for this token (by kid, else first RS256 key).

    python-jose does not resolve ``{"keys": [...]}`` documents itself — pass
    it the individual JWK.
    """
    keys = [k for k in jwks.get("keys", []) if isinstance(k, dict)]
    if not keys:
        raise JWTError("JWKS contains no keys")
    kid = _kid_from_token(token)
    if kid is not None:
        for key in keys:
            if key.get("kid") == kid:
                return key
        raise JWTError("No JWKS key matches token kid")
    for key in keys:
        if key.get("kty") == "RSA":
            return key
    raise JWTError("JWKS contains no RSA key")


def _decode(token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    """Validate signature + expiry, then issuer allow-list, type, audience.

    The issuer check runs HERE, manually, after ``jwt.decode`` has verified
    the signature: the allow-list is env-configurable
    (``KEYCLOAK_ALLOWED_ISSUERS``) and exact-string matched — decoding with
    ``verify_iss`` disabled keeps that policy in our code instead of
    python-jose's single-value ``issuer`` parameter. Audience is also checked
    separately: Keycloak access tokens identify the requesting client via
    ``azp`` (authorized party) and put ``account``-style audiences in
    ``aud`` — the client-id audience only appears when the
    ``access.token.audience`` attribute is set on the client.
    """
    options = {
        "verify_aud": False,  # aud handled explicitly below
        "verify_iss": False,  # allow-list checked explicitly below, post-signature
        "verify_exp": True,
        "verify_iat": True,
        "verify_at_hash": False,
    }
    claims = jwt.decode(
        token,
        _select_key(jwks, token),
        algorithms=["RS256"],
        options=options,
        # NOTE: python-jose has no leeway param; expiry is checked exactly.
        # NTP-level skew between pods is handled by Keycloak's own iat/exp
        # sizing (300s access tokens), not by loosening validation here.
    )
    # Signature/exp/iat are verified above — the claim set is now trustworthy.
    # Issuer: exact string match against the configured allow-list (falls
    # back to [KEYCLOAK_ISSUER] when the setting is empty, so behavior is
    # unchanged out of the box).
    if claims.get("iss") not in settings.KEYCLOAK_EFFECTIVE_ISSUERS:
        raise JWTError("Token issuer is not in the allow-list")
    # Only access tokens may be presented at the API. Keycloak mints
    # typ "Bearer" on access tokens, "ID" on ID tokens and "Refresh" on
    # refresh tokens — an ID token is minted for the same SPA client and
    # would pass the azp check below, so the type is the discriminator that
    # keeps it (and stolen refresh tokens) out of the Authorization header.
    # JWTError here is re-raised as KeycloakTokenError by the caller.
    if claims.get("typ") != "Bearer":
        raise JWTError("Token typ is not Bearer")
    # The token must have been minted for OUR SPA client: azp == client id,
    # or an explicit aud entry when the realm sets access.token.audience.
    expected = settings.KEYCLOAK_AUDIENCE
    azp = claims.get("azp")
    aud = claims.get("aud")
    aud_list = [aud] if isinstance(aud, str) else list(aud or [])
    if azp != expected and expected not in aud_list:
        raise JWTError("Token audience does not match")
    return claims


class KeycloakTokenError(Exception):
    """Token failed Keycloak validation. Carries no token material."""


async def decode_keycloak_token(token: str) -> dict[str, Any]:
    """Validate a Keycloak access token and return its claims.

    Raises:
        KeycloakTokenError: invalid signature, issuer, audience, type, or expiry.

    Flow: decode against the cached JWKS; on ``kid`` miss (key rotation)
    force one refetch and retry once before giving up.
    """
    try:
        jwks = await _get_jwks()
        return _decode(token, jwks)
    except KeycloakTokenError:
        raise
    except JWTError as exc:
        # Unknown kid is the rotation signal — refetch once and retry.
        kid = _kid_from_token(token)
        known = {k.get("kid") for k in (_jwks_cache.get("keys") or {}).get("keys", [])}
        if kid is not None and kid not in known:
            try:
                jwks = await _get_jwks(force=True)
                return _decode(token, jwks)
            except (JWTError, httpx.HTTPError, ValueError):
                raise KeycloakTokenError() from exc
        logger.debug("Keycloak token rejected: %s", exc.__class__.__name__)
        raise KeycloakTokenError() from exc
    except (httpx.HTTPError, ValueError) as exc:
        # JWKS unreachable and nothing cached — fail closed.
        raise KeycloakTokenError() from exc


def reset_jwks_cache() -> None:
    """Test hook: drop the cached JWKS document."""
    _jwks_cache["keys"] = None
    _jwks_cache["fetched_at"] = 0.0
