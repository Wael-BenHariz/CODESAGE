"""
Authentication Routes
OAuth flow, token management, and user authentication.
"""

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

router = APIRouter()

# In-memory state storage (use Redis in production)
oauth_states: dict[str, dict] = {}


def generate_state() -> str:
    """Generate a cryptographically secure state string."""
    return secrets.token_urlsafe(32)


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
    Exchanges code for token and creates/updates user.
    """
    # Verify state
    if state not in oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )
    
    state_data = oauth_states.pop(state)
    
    try:
        # Exchange code for access token
        token_response = await github_service.exchange_code_for_token(code)
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to obtain access token",
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
        
        # Build response
        response = {
            "user_id": str(user.id),
            "login": user.login,
            "access_token": jwt_access,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }
        
        # Add refresh token if available
        if jwt_refresh:
            response["refresh_token"] = jwt_refresh
        
        return response
        
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


# Import datetime for helper functions
from datetime import datetime