"""
Security Dependencies
FastAPI dependencies for authentication and authorization.

Identity authority = Keycloak: access tokens are RS256 JWTs from the realm,
validated in ``app.security.keycloak`` (JWKS / issuer / azp / expiry). The old
HS256 ``token_manager`` no longer authenticates API calls.

``get_current_user`` also:
  * JIT-provisions the local user row on first login (find by keycloak_id,
    else adopt by github_id, else create),
  * syncs ``role`` from the JWT's ``realm_access.roles`` on **every** request
    (the DB column is a mirror — guards never trust a stale value), through
    the four-role model in ``app.security.roles``: unrecognized or missing
    claims derive the read-only sentinel NONE (fail-closed); a token carrying
    the GitHub identity claims (``githubId``/``githubLogin``) with **no**
    recognized/legacy role claim at all still derives DEVELOPER — the
    TEMPORARY (F1) broker fallback, logged with a structured warning each use,
  * keeps the P0 revocation cutoff (logout = reject tokens issued before it).
"""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import GitHubInstallation, User
from app.redis import REVOKED_AT_KEY, get_redis
from app.security.keycloak import KeycloakTokenError, decode_keycloak_token

logger = logging.getLogger(__name__)

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)

# Generic 401 detail — never leak JWT/jose internals in response bodies.
_INVALID_AUTH_DETAIL = "Invalid or expired token"


def _unauthorized(detail: str = _INVALID_AUTH_DETAIL) -> HTTPException:
    """Build a generic 401 with the Bearer challenge header."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _is_revoked(user_id: str, payload: dict) -> bool:
    """Check the token against the per-user logout cutoff.

    ``POST /auth/logout`` stores ``codesage:auth:revoked:{user_id}`` = unix
    time of the cutoff; any access token issued (``iat``) before it is
    rejected — Keycloak tokens are immutable, so an iat cutoff is the only
    server-side revocation lever we own.

    Availability over revocation: Redis failures fail OPEN (log a warning and
    proceed) so an outage cannot lock users out of an otherwise healthy API.
    """
    try:
        cutoff = await get_redis().get(REVOKED_AT_KEY.format(user_id=user_id))
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning(
            "Auth revocation check unavailable (fail-open): %s: %s",
            type(exc).__name__,
            exc,
        )
        return False
    if cutoff is None:
        return False
    try:
        # A missing/non-numeric iat on a revoked account is treated as revoked.
        return float(payload.get("iat", 0)) < float(cutoff)
    except (TypeError, ValueError):
        return True


def _claim_roles(payload: dict) -> list[str]:
    """Realm roles from a Keycloak access token.

    Sources: ``realm_access.roles`` (the ``roles`` client scope), else a flat
    top-level ``roles`` list. A token carrying NEITHER claim was not minted
    with the roles scope (e.g. an ID token replayed as a Bearer token) — it
    must be rejected instead of falling through to the fallback role, which
    would silently upgrade it.

    Raises:
        KeycloakTokenError: neither ``realm_access`` nor ``roles`` present.
            Carries no token material.
    """
    realm_access = payload.get("realm_access")
    if isinstance(realm_access, dict):
        roles = realm_access.get("roles", [])
        if isinstance(roles, list):
            return [str(r) for r in roles]
        # Claim present but not a list — treat as an empty role set so the
        # fallback applies; only *absent* claims are rejected below.
        return []
    # Some setups flatten roles at the top level (client-scope mapper).
    flat = payload.get("roles")
    if isinstance(flat, list):
        return [str(r) for r in flat]
    if realm_access is None and flat is None:
        raise KeycloakTokenError("Token carries no role claim")
    # Present but malformed shape — empty role set, fallback applies.
    return []


def _int_claim(payload: dict, key: str) -> int | None:
    """Best-effort int conversion for the githubId claim."""
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def _via_github(payload: dict) -> bool:
    """True when the token carries GitHub identity claims.

    The ``github-claims`` client scope only maps them from user attributes
    that the GitHub IdP mappers populate at broker login — their presence in
    the JWT means this session authenticated through GitHub.
    """
    return payload.get("githubId") is not None or bool(payload.get("githubLogin"))


async def _find_or_create_user(db: AsyncSession, payload: dict) -> User | None:
    """Resolve (or JIT-provision) the local user for a validated token.

    Lookup order:
      1. ``keycloak_id == sub`` — steady state after first login.
      2. ``github_id == githubId`` claim — adopt pre-Keycloak rows so the
         existing user (installations, watched repos, reviews) is preserved.
      3. Create from claims (invite-only realm — a valid token is enough).

    Returns None only when provisioning fails (e.g. duplicate race resolved
    by another request) and no user can be found.
    """
    from app.security.roles import derive_role  # local: avoids import cycle

    sub = str(payload.get("sub") or "")
    if not sub:
        return None

    result = await db.execute(select(User).where(User.keycloak_id == sub))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    github_id = _int_claim(payload, "githubId")
    if github_id is not None:
        result = await db.execute(select(User).where(User.github_id == github_id))
        user = result.scalar_one_or_none()
        if user is not None:
            # Adopt: link the pre-Keycloak row to its Keycloak identity.
            user.keycloak_id = sub
            await db.commit()
            await db.refresh(user)
            return user

    login = (
        str(payload.get("preferred_username") or "")
        or str(payload.get("githubLogin") or "")
        or sub
    )
    name = payload.get("name") or None
    user = User(
        keycloak_id=sub,
        github_id=github_id,
        login=login[:255],
        email=(str(payload["email"])[:512] if payload.get("email") else None),
        name=(str(name)[:255] if name else None),
        avatar_url=(str(payload["picture"])[:1024] if payload.get("picture") else None),
        role=derive_role(
            _claim_roles(payload),
            via_github=_via_github(payload),
            subject=sub,
        ),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent first login (unique keycloak_id / login) — the other
        # request won; re-read the row it created.
        await db.rollback()
        result = await db.execute(select(User).where(User.keycloak_id == sub))
        user = result.scalar_one_or_none()
        if user is None:
            logger.exception("JIT user provisioning failed for sub=%s", sub)
            return None
    else:
        await db.refresh(user)
        logger.info("Provisioned user %s (login=%s)", user.id, user.login)
    return user


def _sync_profile_and_role(user: User, payload: dict) -> bool:
    """Mirror JWT claims onto the user row. Returns True when anything changed.

    Role is *always* re-derived from this request's token (hard constraint):
    an admin changing a role in Keycloak takes effect on the next request
    without any webhook or cache invalidation.
    """
    from app.security.roles import derive_role  # local: avoids import cycle

    changed = False

    role = derive_role(
        _claim_roles(payload),
        via_github=_via_github(payload),
        subject=str(user.id),
    )
    if user.role != role:
        logger.info("Role sync: user %s %s -> %s", user.id, user.role, role)
        user.role = role
        changed = True

    email = payload.get("email")
    if email and user.email != str(email)[:512]:
        user.email = str(email)[:512]
        changed = True
    picture = payload.get("picture")
    if picture and user.avatar_url != str(picture)[:1024]:
        user.avatar_url = str(picture)[:1024]
        changed = True
    return changed


async def _adopt_github_installation(db: AsyncSession, user: User) -> None:
    """Heal a missing ``users.github_installation_id`` from ``github_installations``.

    The link is normally written by the signed-state install callback or the
    ``installation`` webhook. When neither fired (e.g. the GitHub App Setup
    URL is unset so the callback never arrives), adopt the newest
    installation owned by this user's GitHub account so /github/status,
    /github/repos and webhook owner-resolution keep resolving.

    No-op when the link already exists or the row has no GitHub identity
    (console-only users). The link is never *replaced* — only a NULL is
    healed, so the webhook/callback value stays authoritative.
    """
    if user.github_installation_id is not None or user.github_id is None:
        return
    result = await db.execute(
        select(GitHubInstallation)
        .where(GitHubInstallation.account_id == user.github_id)
        .order_by(GitHubInstallation.created_at.desc())
        .limit(1)
    )
    installation = result.scalar_one_or_none()
    if installation is None:
        return
    # Capture before commit(): commit expires every attribute in the session
    # and a lazy re-read would raise MissingGreenlet in async context.
    new_installation_id = installation.installation_id
    user.github_installation_id = new_installation_id
    await db.commit()
    await db.refresh(user)
    logger.info(
        "Adopted GitHub installation %s for user %s (account %s)",
        new_installation_id,
        user.login,
        user.github_id,
    )


async def _authenticate(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> User | None:
    """Shared core: validate the Keycloak token and resolve the user.

    Returns the user, or None when identity could not be established (any
    failure class — callers decide between 401 and silent None).
    """
    if not credentials:
        return None

    try:
        payload = await decode_keycloak_token(credentials.credentials)
        # Reject role-less tokens here, before any user resolution: a token
        # with neither realm_access nor a flat roles claim must 401, not
        # inherit the fallback role (KeycloakTokenError → caller returns
        # None → generic 401).
        _claim_roles(payload)
    except KeycloakTokenError:
        logger.warning("Access token verification failed")
        return None

    user = await _find_or_create_user(db, payload)
    if user is None:
        return None

    # Self-heal the user<->installation link before any endpoint reads it.
    await _adopt_github_installation(db, user)

    if await _is_revoked(str(user.id), payload):
        logger.info("Rejected revoked token for user %s", user.id)
        return None

    if _sync_profile_and_role(user, payload):
        await db.commit()
        # commit() expires all attributes; refresh now (in async context) so
        # response serialization never triggers a sync refresh (MissingGreenlet).
        await db.refresh(user)

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> User:
    """
    Dependency to get the current authenticated user.

    Raises:
        HTTPException: If no valid Keycloak token is provided (generic 401).
    """
    if not credentials:
        raise _unauthorized("Not authenticated")

    user = await _authenticate(credentials, db)
    if user is None:
        raise _unauthorized()
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(  # noqa: B008
        bearer_scheme
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> User | None:
    """Current user when authenticated, None otherwise (never raises 401)."""
    return await _authenticate(credentials, db)


async def require_admin(
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> User:
    """Require PLATFORM_ADMIN (kept for backward-compat imports).

    Literal instead of ``ROLE_PLATFORM_ADMIN``: ``roles.py`` imports this
    module, so importing it here would create a cycle.
    """
    if current_user.role != "PLATFORM_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return current_user


async def require_repository_access(
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> User:
    """
    Dependency to require access to a specific repository.

    Should be used with a path parameter for repository_id.
    """
    # This is a placeholder - implement repository-level access control
    return current_user
