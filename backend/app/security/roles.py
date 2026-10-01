"""Realm-role derivation and FastAPI role guards.

Roles always come from the validated Keycloak JWT's ``realm_access.roles``
claim — the DB column is only a synced mirror written by ``get_current_user``
on every request; guards never trust a stale stored value.
"""

from fastapi import Depends, HTTPException, status

from app.db.models import User
from app.security.dependencies import get_current_user

ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_DEVELOPER = "DEVELOPER"
ROLE_GUEST = "GUEST"

VALID_ROLES = (ROLE_SUPER_ADMIN, ROLE_DEVELOPER, ROLE_GUEST)


def derive_role(token_roles: list[str], *, via_github: bool = False) -> str:
    """Map Keycloak realm roles to the single app role for this request.

    Precedence: SUPER_ADMIN > GUEST > DEVELOPER.

    GUEST outranks DEVELOPER so an explicit read-only downgrade in Keycloak
    wins even if the user also carries DEVELOPER (e.g. via a default role).

    No recognized role → fallback: ``via_github=True`` (token carries the
    GitHub identity claims ``githubId``/``githubLogin`` — a session that came
    through the GitHub broker) derives DEVELOPER, so GitHub sign-ins get a
    usable role without an admin assigning one in Keycloak. Anything else
    falls back to GUEST (fail-closed): a non-GitHub token whose realm roles
    are only realm defaults (``default-roles-*``) stays read-only until an
    admin assigns a role explicitly. A token with no role claim at all
    never reaches this function — ``_claim_roles`` rejects it with a 401.
    """
    roles = {r.upper() for r in token_roles if isinstance(r, str)}
    if ROLE_SUPER_ADMIN in roles:
        return ROLE_SUPER_ADMIN
    if ROLE_GUEST in roles:
        return ROLE_GUEST
    if ROLE_DEVELOPER in roles:
        return ROLE_DEVELOPER
    if via_github:
        return ROLE_DEVELOPER
    return ROLE_GUEST


def _forbidden() -> HTTPException:
    """403 with a generic detail — never leak which roles exist."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


def require_role(*allowed: str):
    """Dependency factory: authenticated + ``user.role`` in *allowed*.

    ``get_current_user`` has already synced ``user.role`` from this request's
    JWT, so the check runs against the token, not the stored column.
    """

    if not allowed:
        raise ValueError("require_role needs at least one allowed role")
    unknown = set(allowed) - set(VALID_ROLES)
    if unknown:
        raise ValueError(f"Unknown role(s): {sorted(unknown)}")

    async def dependency(
        current_user: User = Depends(get_current_user),  # noqa: B008
    ) -> User:
        if current_user.role not in allowed:
            raise _forbidden()
        return current_user

    return dependency


# Route-table shorthands (Step 8):
#   reads            → any authenticated role (GUEST included, read-only)
#   mutations        → require_developer  (DEVELOPER or SUPER_ADMIN)
#   user admin       → require_super_admin
require_developer = require_role(ROLE_SUPER_ADMIN, ROLE_DEVELOPER)
require_super_admin = require_role(ROLE_SUPER_ADMIN)
