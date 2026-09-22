"""
Authentication Routes
OAuth flow, token management, and user authentication.
"""

import secrets
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt

from app.config import settings
from app.db import get_db
from app.db.models import User, OAuthToken
from app.schemas.auth import (
    Token,
    OAuthState,
    OAuthCallback,
    AuthResponse,
    GitHubUserInfo,
)
from app.schemas.user import UserResponse
from app.security.jwt import create_access_token, create_refresh_token, verify_token
from app.security.dependencies import get_current_user
from app.services.github import github_service

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory state storage (use Redis in production)
oauth_states: dict[str, dict] = {}


def generate_state() -> str:
    """Generate a cryptographically secure state string."""
    return secrets.token_urlsafe(32)


def _create_installation_state_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now - timedelta(seconds=60),
        "exp": now + timedelta(minutes=10),
        "type": "github_app_installation_state",
    }
    return jwt.encode(payload, settings.STATE_TOKEN_SECRET, algorithm=settings.ALGORITHM)


def _verify_installation_state_token(state_token: str) -> str:
    payload = jwt.decode(state_token, settings.STATE_TOKEN_SECRET, algorithms=[settings.ALGORITHM])
    if payload.get("type") != "github_app_installation_state":
        raise JWTError("Invalid installation state token")
    user_id = payload.get("sub")
    if not user_id:
        raise JWTError("Missing user identifier in installation state token")
    return str(user_id)


@router.get("/github")
async def github_login(
    request: Request,
    redirect_url: str = Query(None, description="URL to redirect after OAuth"),
):
    """
    Initiate GitHub OAuth flow.
    Returns the GitHub authorization URL.
    """
    state = generate_state()
    
    # Default redirect URL to frontend callback
    if not redirect_url:
        redirect_url = "http://localhost:4200/auth/callback"
    
    # Store state with redirect URL
    oauth_states[state] = {
        "redirect_url": redirect_url,
        "created_at": datetime.now(timezone.utc),
    }
    
    # Generate authorization URL
    auth_url = github_service.get_oauth_login_url(state, redirect_url)
    
    return {
        "authorization_url": auth_url,
        "state": state,
    }


@router.get("/github/callback")
async def github_callback(
    code: str = Query(..., description="Authorization code from GitHub"),
    state: str = Query(..., description="State parameter for CSRF verification"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle GitHub OAuth callback.
    Exchanges code for token, creates/updates user, then redirects to frontend with JWT.
    """
    logger.info(f"OAuth callback received - state: {state[:10]}..., code length: {len(code)}")
    
    # Verify state
    if state not in oauth_states:
        logger.error(f"Invalid state - available states: {list(oauth_states.keys())}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )
    
    state_data = oauth_states.pop(state)
    logger.info(f"State verified - redirect_url: {state_data.get('redirect_url')}")
    
    try:
        # Exchange code for access token
        logger.info("Exchanging code for token...")
        token_response = await github_service.exchange_code_for_token(code)
        logger.info(f"Token response keys: {list(token_response.keys())}")
        
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        
        if not access_token:
            logger.error(f"No access token in response: {token_response}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to obtain access token from GitHub",
            )
        
        # Get user info from GitHub
        logger.info("Fetching user info from GitHub...")
        github_user = await github_service.get_user_info(access_token)
        logger.info(f"GitHub user: {github_user.get('login')}")
        
        # Find or create user
        user = await _get_or_create_user(db, github_user)
        logger.info(f"User created/found: {user.id}")
        
        # Store/update OAuth token
        await _store_token(db, user.id, access_token, refresh_token, token_response)
        
        # Generate JWT tokens
        jwt_access = create_access_token(str(user.id))
        jwt_refresh = create_refresh_token(str(user.id))
        
        # Redirect to frontend with JWT token
        frontend_url = state_data.get("redirect_url", "http://localhost:4200/auth/callback")
        redirect_url = f"{frontend_url}?token={jwt_access}&refresh_token={jwt_refresh}"
        logger.info(f"Redirecting to frontend: {frontend_url}")
        
        return RedirectResponse(url=redirect_url)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth flow failed with exception: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth flow failed: {type(e).__name__}: {str(e)}",
        )


class FrontendCallback(BaseModel):
    """Frontend OAuth callback with just the code."""
    code: str = Field(..., description="Authorization code from GitHub")


@router.post("/github/callback")
async def github_callback_from_frontend(
    body: FrontendCallback,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle GitHub OAuth callback from frontend SPA.
    Frontend sends the code after GitHub redirects to it.
    """
    try:
        # Exchange code for access token
        token_response = await github_service.exchange_code_for_token(body.code)
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to obtain access token from GitHub",
            )
        
        # Get user info from GitHub
        github_user = await github_service.get_user_info(access_token)
        
        # Find or create user
        user = await _get_or_create_user(db, github_user)
        
        # Store/update OAuth token
        await _store_token(db, user.id, access_token, refresh_token, token_response)
        
        # Generate JWT tokens
        jwt_access = create_access_token(str(user.id))
        jwt_refresh = create_refresh_token(str(user.id))
        
        return {
            "user": UserResponse.model_validate(user),
            "access_token": jwt_access,
            "refresh_token": jwt_refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth flow failed: {str(e)}",
        )


@router.post("/refresh")
async def refresh_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Refresh an expired access token using a refresh token.
    """
    try:
        payload = verify_token(refresh_token, token_type="refresh")
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        
        # Verify user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        # Generate new access token
        new_access_token = create_access_token(user_id)
        
        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }
        
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """
    Get current authenticated user's information.
    """
    return UserResponse.model_validate(current_user)


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Logout current user (revoke OAuth token).
    """
    # Delete OAuth tokens for this user
    await db.execute(
        select(OAuthToken)
        .where(OAuthToken.user_id == current_user.id)
    )
    
    # In production, you'd also revoke the GitHub token
    
    return {"message": "Logged out successfully"}


@router.get("/github/app/install-url")
async def get_github_app_install_url(
    current_user: User = Depends(get_current_user),
):
    """Generate the GitHub App installation URL with a signed state token."""

    if not settings.GITHUB_APP_SLUG:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub App slug is not configured",
        )

    state_token = _create_installation_state_token(str(current_user.id))
    url = f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?{urlencode({'state': state_token})}"
    return {"url": url}


@router.get("/github/app/callback")
async def github_app_callback(
    installation_id: int = Query(..., description="GitHub App installation ID"),
    setup_action: str = Query(..., description="GitHub installation setup action"),
    state: str | None = Query(None, description="Signed installation state token"),
    db: AsyncSession = Depends(get_db),
):
    """Persist the GitHub App installation on the signed-in user and redirect home."""

    frontend_url = settings.FRONTEND_URL.rstrip("/")

    # Step 2: no state token means we cannot identify the user — do not proceed.
    if not state:
        return RedirectResponse(url=f"{frontend_url}/github/callback?success=false")

    try:
        user_id = _verify_installation_state_token(state)
        user_uuid = UUID(user_id)
    except (JWTError, ValueError):
        return RedirectResponse(url=f"{frontend_url}/github/callback?success=false")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url=f"{frontend_url}/github/callback?success=false")

    user.github_installation_id = installation_id
    await db.commit()

    return RedirectResponse(url=f"{frontend_url}/github/callback?success=true")


# ==================== Helper Functions ====================

async def _get_or_create_user(
    db: AsyncSession,
    github_user: dict,
) -> User:
    """Find existing user by GitHub ID or create new one."""
    
    github_id = github_user["id"]
    
    # Try to find existing user
    result = await db.execute(
        select(User).where(User.github_id == github_id)
    )
    user = result.scalar_one_or_none()
    
    if user:
        # Update user info
        user.login = github_user.get("login", user.login)
        user.name = github_user.get("name")
        user.email = github_user.get("email")
        user.avatar_url = github_user.get("avatar_url")
        await db.commit()
        return user
    
    # Create new user
    user = User(
        github_id=github_id,
        login=github_user["login"],
        name=github_user.get("name"),
        email=github_user.get("email"),
        avatar_url=github_user.get("avatar_url"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return user


async def _store_token(
    db: AsyncSession,
    user_id: str,
    access_token: str,
    refresh_token: str,
    token_response: dict,
) -> None:
    """Store or update OAuth token for user."""
    
    from datetime import datetime, timezone
    
    # Calculate expiration
    expires_in = token_response.get("expires_in", 3600 * 8)  # Default 8 hours
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    
    # Find existing token or create new
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == user_id)
    )
    token = result.scalar_one_or_none()
    
    if token:
        token.access_token = access_token
        token.refresh_token = refresh_token
        token.expires_at = expires_at
    else:
        token = OAuthToken(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        db.add(token)
    
    await db.commit()
