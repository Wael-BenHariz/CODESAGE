"""Four-role model: derivation from the Keycloak JWT + FastAPI role guards.

Roles come from the validated access token's ``realm_access.roles`` claim (or
the flat ``roles`` claim). The DB ``users.role`` column is only a synced
mirror written by ``get_current_user`` — guards never trust it.

The four roles form a strict ladder (high → low):

    PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER

``NONE`` is an internal, read-only sentinel (fail-closed): it has **no
ladder position**, is never assignable in Keycloak and never stored in
``org_members``. It derives from unrecognized/missing role claims and from
the legacy ``GUEST`` claim via the one-release compatibility map.

Layout (v0.3.0, docs/PLAN_ROLES_SETTINGS_STAGED.md §2):
  - legacy claims (``SUPER_ADMIN``, ``GUEST``) are mapped through
    ``_COMPAT_MAP`` — **remove in v0.4.0** together with the old realm
    roles/groups;
  - the GitHub-broker ``DEVELOPER`` fallback (F1) is **temporary** — remove
    once every realm user has a group.
"""

import logging

from fastapi import Depends, HTTPException, status

from app.db.models import User
from app.security.dependencies import get_current_user

logger = logging.getLogger(__name__)

# --- the four roles + the internal read-only sentinel ------------------------

ROLE_PLATFORM_ADMIN = "PLATFORM_ADMIN"
ROLE_ORG_ADMIN = "ORG_ADMIN"
ROLE_REVIEWER = "REVIEWER"
ROLE_DEVELOPER = "DEVELOPER"

# Internal sentinel: read-only, no ladder position, not assignable, never
# stored in org_members. Derivation only.
ROLE_NONE = "NONE"

# Legacy claim names — accepted through _COMPAT_MAP for one release only.
ROLE_SUPER_ADMIN = "SUPER_ADMIN"  # legacy, compat only — remove in v0.4.0
ROLE_GUEST = "GUEST"  # legacy, compat only — remove in v0.4.0

VALID_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_ORG_ADMIN,
    ROLE_REVIEWER,
    ROLE_DEVELOPER,
    ROLE_NONE,
)

# One-release compatibility map: legacy claim -> new claim.
# TODO(v0.4.0): remove together with the old realm roles/groups.
_COMPAT_MAP = {
    ROLE_SUPER_ADMIN: ROLE_PLATFORM_ADMIN,
    ROLE_GUEST: ROLE_NONE,
    ROLE_DEVELOPER: ROLE_DEVELOPER,
}


def derive_role(
    token_roles,
    *,
    via_github: bool = False,
    subject: str | None = None,
) -> str:
    """Map a token's realm-role claims to this request's effective global role.

    Order matters:

    1. Claims pass through the one-release compat map
       (``SUPER_ADMIN→PLATFORM_ADMIN``, ``GUEST→NONE``, ``DEVELOPER→
       DEVELOPER``); new names pass through unchanged.
    2. Precedence: ``PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER >
       DEVELOPER`` — an explicit legacy read-only claim (``GUEST`` → ``NONE``)
       beats role grants, mirroring today's ``SUPER_ADMIN > GUEST >
       DEVELOPER`` (fail-closed: an explicit downgrade is honored).
    3. **No recognized or legacy claim at all** (e.g. only ``default-roles-*``
       or an unknown name):
       - **TEMPORARY (F1)** and ``via_github`` (GitHub-brokered session) →
         ``DEVELOPER`` — the pre-existing broker behavior (commit 183ffd9)
         kept so GitHub sign-ins stay usable without a Keycloak role
         assignment. Logs a structured warning (subject, derived role, no
         secrets) each time. **Remove once every realm user has a group**
         (plan §6 follow-up);
       - otherwise → ``NONE`` (fail-closed).

    A token with *no* role claim at all never reaches this function —
    ``_claim_roles`` rejects it with a 401 first.
    """
    roles = {r.upper() for r in token_roles if isinstance(r, str)}
    mapped = {_COMPAT_MAP.get(r, r) for r in roles}

    if ROLE_PLATFORM_ADMIN in mapped:
        return ROLE_PLATFORM_ADMIN
    if ROLE_NONE in mapped:  # explicit legacy read-only downgrade wins
        return ROLE_NONE
    for role in (ROLE_ORG_ADMIN, ROLE_REVIEWER, ROLE_DEVELOPER):
        if role in mapped:
            return role

    # Reached only when no recognized/legacy claim matched the ladder above.
    if via_github:
        # TEMPORARY (F1): GitHub-brokered sessions keep deriving DEVELOPER
        # until every realm user has a group — plan §6 follow-up.
        logger.warning(
            "role_fallback_broker_developer subject=%s derived=%s claims=%s",
            subject or "unknown",
            ROLE_DEVELOPER,
            sorted(roles),
        )
        return ROLE_DEVELOPER
    return ROLE_NONE


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
#   reads            → any authenticated role (get_current_user; NONE reads too)
#   mutations        → require_developer    (all four roles, NONE excluded)
#   review validate  → require_reviewer     (REVIEWER+; Step 9)
#   user admin       → require_super_admin  (PLATFORM_ADMIN)
require_developer = require_role(
    ROLE_PLATFORM_ADMIN, ROLE_ORG_ADMIN, ROLE_REVIEWER, ROLE_DEVELOPER
)
require_reviewer = require_role(ROLE_PLATFORM_ADMIN, ROLE_ORG_ADMIN, ROLE_REVIEWER)
require_super_admin = require_role(ROLE_PLATFORM_ADMIN)
