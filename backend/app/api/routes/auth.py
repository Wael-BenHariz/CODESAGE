"""
Authentication Routes
Keycloak-owned identity: the backend never mints or refreshes login tokens.

Kept endpoints:
  * GET  /keycloak/config       — public SPA bootstrap (Keycloak URL/realm/client)
  * GET  /me                    — current user (Keycloak JWT)
  * POST /logout                — revoke tokens issued before now + purge
                                  stored OAuth material
  * GET  /github/app/install-url  — signed-state GitHub App install flow
  * GET  /github/app/callback     — persist installation on the signed-in user

Removed (identity moved to Keycloak):
  * GET  /github            — OAuth initiate (frontend uses keycloak.login)
  * GET  /github/callback   — OAuth code exchange (Keycloak broker owns it)
  * POST /refresh           — Keycloak issues/rotates refresh tokens
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwt
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.models import GitHubInstallation, OAuthToken, User
from app.redis import REVOKED_AT_KEY, get_redis
from app.schemas.user import MeResponse, UserResponse, WorkspaceSummary
from app.security.dependencies import bearer_scheme, get_current_user
from app.security.keycloak import KeycloakTokenError, decode_keycloak_token
from app.security.workspace_access import (
    capability_flags,
    check_permission_in_workspace,
    list_user_workspaces,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _not_authorized() -> HTTPException:
    """Generic 401: identity could not be established (no internals leaked)."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _create_installation_state_token(
    user_id: str, workspace_id: str | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": str(user_id),
        "iat": now - timedelta(seconds=60),
        "exp": now + timedelta(minutes=10),
        "type": "github_app_installation_state",
    }
    if workspace_id:
        # Workspace the admin chose to install into — the callback binds the
        # github_installations row to it (§2.1: installations live in a
        # workspace). Omitted for the legacy no-workspace flow.
        payload["wid"] = workspace_id
    return jwt.encode(
        payload, settings.STATE_TOKEN_SECRET, algorithm=settings.ALGORITHM
    )


def _verify_installation_state_token(state_token: str) -> tuple[str, UUID | None]:
    payload = jwt.decode(
        state_token, settings.STATE_TOKEN_SECRET, algorithms=[settings.ALGORITHM]
    )
    if payload.get("type") != "github_app_installation_state":
        raise JWTError("Invalid installation state token")
    user_id = payload.get("sub")
    if not user_id:
        raise JWTError("Missing user identifier in installation state token")
    wid = payload.get("wid")
    try:
        workspace_id = UUID(str(wid)) if wid else None
    except (TypeError, ValueError):
        raise JWTError("Malformed workspace id in installation state token") from None
    return str(user_id), workspace_id


def _keycloak_browser_url() -> str:
    """Browser-facing Keycloak base: explicit public URL or FRONTEND_URL+/auth."""
    if settings.KEYCLOAK_PUBLIC_URL:
        return settings.KEYCLOAK_PUBLIC_URL.rstrip("/")
    return f"{settings.FRONTEND_URL.rstrip('/')}/auth"


@router.get("/keycloak/config")
async def keycloak_config() -> dict[str, str]:
    """Public SPA bootstrap: where Keycloak lives and which client to use.

    Deliberately unauthenticated — the Angular app fetches this before it has
    any token, then hands it to keycloak-js init().
    """
    return {
        "url": _keycloak_browser_url(),
        "realm": settings.KEYCLOAK_REALM,
        "clientId": "codesage-angular",
    }


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Get current authenticated user's information (role synced from JWT).

    Enriched for RBAC (target design §2.3/§2.4): ``workspaces`` lists every
    workspace the user belongs to with the *effective* role (ladder max of
    realm role and membership) and its capability flags, and
    ``capabilities`` mirrors the flags of the global realm role. The
    frontend renders from these flags — it never re-derives role lists.
    """
    memberships = await list_user_workspaces(db, current_user)
    payload = UserResponse.model_validate(current_user).model_dump()
    return MeResponse(
        **payload,
        workspaces=[
            WorkspaceSummary(
                id=str(workspace.id),
                name=workspace.name,
                type=workspace.type,
                role=role,
                capabilities=capability_flags(role),
                is_personal=workspace.type == "PERSONAL",
            )
            for workspace, role in memberships
        ],
        capabilities=capability_flags(current_user.role),
    )


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(  # noqa: B008
        bearer_scheme,
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Revoke this user's API access: purge stored OAuth material and reject
    any access token issued before this moment.

    The Keycloak session itself is ended client-side (keycloak.logout());
    Keycloak refresh tokens are Keycloak's business, not ours.
    """
    if not credentials:
        raise _not_authorized()

    try:
        payload = await decode_keycloak_token(credentials.credentials)
    except KeycloakTokenError:
        raise _not_authorized() from None

    sub = str(payload.get("sub") or "")
    result = await db.execute(select(User).where(User.keycloak_id == sub))
    user = result.scalar_one_or_none()
    if user is None:
        raise _not_authorized()

    # Real delete — stored GitHub OAuth material is dead on logout.
    await db.execute(delete(OAuthToken).where(OAuthToken.user_id == user.id))
    await db.commit()

    try:
        await get_redis().set(  # type: ignore[misc]
            REVOKED_AT_KEY.format(user_id=user.id),
            time.time(),
            ex=2100,  # > access-token lifespan (Keycloak default 300s)
        )
    except RedisError:
        logger.exception("Logout revocation update failed for user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed",
        ) from None

    return {"message": "Logged out successfully"}


@router.get("/github/app/install-url")
async def get_github_app_install_url(
    workspace_id: UUID | None = Query(  # noqa: B008
        None, description="Workspace to install the GitHub App into"
    ),
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Generate the GitHub App installation URL with a signed state token.

    Installing the App is ``repo_admin`` in the target workspace (ORG_ADMIN+,
    §2.3): pass ``workspace_id`` and the caller is checked there — unknown
    workspace / non-member → 404, under-role → 403. The chosen workspace is
    signed into the state (``wid``) and written back on the callback.
    Omitting ``workspace_id`` keeps the legacy unbound flow (the webhook +
    org provisioning binds the installation afterwards).
    """

    if not settings.GITHUB_APP_SLUG:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub App slug is not configured",
        )

    if workspace_id is not None:
        await check_permission_in_workspace(
            db, current_user, workspace_id, "repo_admin"
        )

    state_token = _create_installation_state_token(
        str(current_user.id),
        str(workspace_id) if workspace_id else None,
    )
    url = f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?{urlencode({'state': state_token})}"
    return {"url": url}


@router.get("/github/app/callback")
async def github_app_callback(
    installation_id: int = Query(..., description="GitHub App installation ID"),
    setup_action: str = Query(..., description="GitHub installation setup action"),
    state: str | None = Query(None, description="Signed installation state token"),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Persist the GitHub App installation on the signed-in user and redirect home."""

    frontend_url = settings.FRONTEND_URL.rstrip("/")

    # Step 2: no state token means we cannot identify the user — do not proceed.
    if not state:
        return RedirectResponse(url=f"{frontend_url}/github/callback?success=false")

    try:
        user_id, workspace_id = _verify_installation_state_token(state)
        user_uuid = UUID(user_id)
    except (JWTError, ValueError):
        return RedirectResponse(url=f"{frontend_url}/github/callback?success=false")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url=f"{frontend_url}/github/callback?success=false")

    user.github_installation_id = installation_id

    # Bind the installation to the workspace the admin picked in the signed
    # state (§2.1 — installations live in exactly one workspace). Existing
    # bindings are never overwritten (precedence: first binding wins); when
    # the webhook has not created the row yet, org provisioning binds it on
    # delivery instead (state `wid` was consumed here, the row was not there
    # to write to — the auto-created ORG workspace is the heal path).
    if workspace_id is not None:
        install_result = await db.execute(
            select(GitHubInstallation).where(
                GitHubInstallation.installation_id == installation_id
            )
        )
        installation_row = install_result.scalar_one_or_none()
        if installation_row is not None and installation_row.workspace_id is None:
            installation_row.workspace_id = workspace_id
    await db.commit()

    # Org provisioning (Step 3): seed the org + the linker's membership
    # (least-privilege rule). Best-effort: a failure here must not break
    # the install redirect — the `installation created` webhook and
    # `scripts/org_seed_report.py --apply` are the heal paths.
    try:
        from app.services.org_provisioning import provision_for_user_link

        await provision_for_user_link(db, user)
        await db.commit()
    except Exception:  # best-effort by design — never break the redirect
        logger.exception(
            "Org provisioning failed after install callback "
            "(user=%s installation=%s)",
            user.id,
            installation_id,
        )
        await db.rollback()

    # No token pair in the redirect: Keycloak owns tokens now. The SPA keeps
    # its session in localStorage and keycloak-js re-establishes it (silent
    # check-sso iframe) when /github/callback boots.
    return RedirectResponse(url=f"{frontend_url}/github/callback?success=true")
