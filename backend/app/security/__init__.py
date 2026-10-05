"""
Security Utilities Package
Keycloak RS256 validation, role guards, and encryption helpers.

The legacy HS256 ``TokenManager`` (jwt.py) was removed when Keycloak became
the token authority — the backend only *validates* tokens now (keycloak.py).
"""

from app.security.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_admin,
)
from app.security.keycloak import KeycloakTokenError, decode_keycloak_token
from app.security.roles import (
    ROLE_DEVELOPER,
    ROLE_GUEST,
    ROLE_NONE,
    ROLE_ORG_ADMIN,
    ROLE_PLATFORM_ADMIN,
    ROLE_REVIEWER,
    ROLE_SUPER_ADMIN,
    derive_role,
    require_developer,
    require_reviewer,
    require_role,
    require_super_admin,
)

__all__ = [
    "ROLE_DEVELOPER",
    "ROLE_GUEST",  # legacy claim name (compat map) — remove in v0.4.0
    "ROLE_NONE",
    "ROLE_ORG_ADMIN",
    "ROLE_PLATFORM_ADMIN",
    "ROLE_REVIEWER",
    "ROLE_SUPER_ADMIN",  # legacy claim name (compat map) — remove in v0.4.0
    "KeycloakTokenError",
    "decode_keycloak_token",
    "derive_role",
    "get_current_user",
    "get_current_user_optional",
    "require_admin",
    "require_developer",
    "require_reviewer",
    "require_role",
    "require_super_admin",
]
