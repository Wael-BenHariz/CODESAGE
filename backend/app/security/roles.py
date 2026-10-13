"""Four-role model: derivation from the Keycloak JWT + FastAPI role guards.

Roles come from the validated access token's ``realm_access.roles`` claim (or
the flat ``roles`` claim). The DB ``users.role`` column is only a synced
mirror written by ``get_current_user`` — guards never trust it.

The four roles form a strict ladder (high → low):

    PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE

``NONE`` is an internal, read-only sentinel (fail-closed): it has **no
ladder position**, is never assignable in Keycloak and never stored in
``org_members``. It derives from unrecognized/missing role claims and from
the legacy ``GUEST`` claim via the one-release compatibility map.

Layout (v0.4.0):
  - legacy claims (``SUPER_ADMIN``, ``GUEST``) are mapped through
    ``_COMPAT_MAP`` — **removed in v0.4.0** together with the old realm
    roles/groups;
  - the GitHub-broker ``DEVELOPER`` fallback (F1) is **removed** — a
    GitHub-brokered session with no recognized claim derives
    ``ORG_ADMIN`` (the account-creation default, decisions #11/#12:
    the signup role; inside an org the invitation's ``org_members``
    role wins instead). Any explicit claim still outranks the default,
    and non-brokered tokens without a recognized claim stay fail-closed
    ``NONE``.
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
    2. Precedence: ``PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER >
       NONE`` — an explicit legacy read-only claim (``GUEST`` → ``NONE``)
       is treated as the lowest rank (fail-closed: an explicit downgrade
       is honored but still below DEVELOPER).
    3. **No recognized or legacy claim at all** (e.g. only ``default-roles-*``
       or an unknown name):
       - ``via_github`` (GitHub-brokered session) → ``ORG_ADMIN``
         (the account-creation default — decisions #11/#12: a GitHub
         signup starts as ORG_ADMIN globally; an explicit claim above
         still outranks it, and inside any org the invitation's
         ``org_members`` role decides);
       - otherwise → ``NONE`` (fail-closed).

    A token with *no* role claim at all never reaches this function —
    ``_claim_roles`` rejects it with a 401 first.
    """
    roles = {r.upper() for r in token_roles if isinstance(r, str)}
    mapped = {_COMPAT_MAP.get(r, r) for r in roles}

    if ROLE_PLATFORM_ADMIN in mapped:
        return ROLE_PLATFORM_ADMIN
    for role in (ROLE_ORG_ADMIN, ROLE_REVIEWER, ROLE_DEVELOPER):
        if role in mapped:
            return role
    if ROLE_NONE in mapped:  # explicit legacy read-only downgrade
        return ROLE_NONE
    # No recognized or legacy claim at all:
    # GitHub-brokered signup default → ORG_ADMIN, otherwise fail closed.
    if via_github:
        return ROLE_ORG_ADMIN
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
#   mutations        → require_developer    (all roles except NONE)
#   review validate  → require_reviewer     (REVIEWER+; Step 9)
#   user admin       → require_super_admin  (PLATFORM_ADMIN)
require_developer = require_role(
    ROLE_PLATFORM_ADMIN, ROLE_ORG_ADMIN, ROLE_REVIEWER, ROLE_DEVELOPER
)
require_reviewer = require_role(ROLE_PLATFORM_ADMIN, ROLE_ORG_ADMIN, ROLE_REVIEWER)
require_super_admin = require_role(ROLE_PLATFORM_ADMIN)

# ---------------------------------------------------------------------------
# Capability flags — single source of truth for ``GET /auth/me``'s
# ``capabilities`` payload. The SPA renders nav/route gating from
# ``capability_flags(role)`` instead of re-deriving role lists, so a rule
# change lands in exactly one place (this map) on the backend.
# ---------------------------------------------------------------------------

#: ladder rank; NONE ranks lowest (read-only sentinel, never outranks).
RANK: dict[str, int] = {
    ROLE_NONE: 0,
    ROLE_DEVELOPER: 1,
    ROLE_REVIEWER: 2,
    ROLE_ORG_ADMIN: 3,
    ROLE_PLATFORM_ADMIN: 4,
}

#: Roles that carry a real ladder position (usable as a minimum requirement).
LADDER_ROLES = (ROLE_DEVELOPER, ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN)

VIEW_ROLES = [
    ROLE_NONE,
    ROLE_DEVELOPER,
    ROLE_REVIEWER,
    ROLE_ORG_ADMIN,
    ROLE_PLATFORM_ADMIN,
]
TRIGGER_ROLES = [ROLE_DEVELOPER, ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REQUEST_ROLES = [ROLE_DEVELOPER, ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REVIEW_ROLES = [ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REPO_CONFIG_ROLES = [ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REPO_ADMIN_ROLES = [ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
PLATFORM_ROLES = [ROLE_PLATFORM_ADMIN]

#: permission name -> every role allowed to perform it.
PERMISSION_MAP: dict[str, list[str]] = {
    "view": VIEW_ROLES,
    "trigger": TRIGGER_ROLES,
    "request": REQUEST_ROLES,
    "review": REVIEW_ROLES,
    "repo_config": REPO_CONFIG_ROLES,
    "repo_admin": REPO_ADMIN_ROLES,
    "platform": PLATFORM_ROLES,
}

#: permission -> the *lowest* role that satisfies it (the threshold).
_MIN_ROLE: dict[str, str] = {
    name: min(roles, key=lambda r: RANK[r]) for name, roles in PERMISSION_MAP.items()
}


def min_role_for(permission: str) -> str:
    """Lowest role satisfying ``permission`` (raises on an unknown name)."""
    try:
        return _MIN_ROLE[permission]
    except KeyError:  # pragma: no cover - programming error, fail fast at import
        raise ValueError(
            f"unknown permission {permission!r}; expected one of {sorted(PERMISSION_MAP)}"
        ) from None


def allowed(permission: str, role: str) -> bool:
    """Is ``role`` allowed to perform ``permission``? (No DB — pure matrix.)"""
    return RANK.get(role, RANK[ROLE_NONE]) >= RANK[min_role_for(permission)]


def capability_flags(role: str) -> dict[str, bool]:
    """Permission flags for the *global* realm role, as ``GET /auth/me``
    presents them.

    The frontend renders from these instead of re-deriving role lists, so
    a rule change lands in exactly one place (this function).
    """
    return {
        "view": allowed("view", role),
        "trigger": allowed("trigger", role),
        "request": allowed("request", role),
        "review": allowed("review", role),
        "repo_config": allowed("repo_config", role),
        "repo_admin": allowed("repo_admin", role),
        "platform": allowed("platform", role),
    }
