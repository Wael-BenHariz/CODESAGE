"""
Authentication Schemas
Request/Response models for OAuth and JWT authentication.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    """JWT access token response."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration in seconds")
    refresh_token: Optional[str] = Field(None, description="Refresh token for token renewal")


class TokenPayload(BaseModel):
    """JWT token payload content."""

    sub: str = Field(..., description="Subject (user ID)")
    exp: datetime = Field(..., description="Expiration timestamp")
    iat: datetime = Field(..., description="Issued at timestamp")
    type: str = Field(default="access", description="Token type: access or refresh")


class OAuthState(BaseModel):
    """OAuth state parameter for CSRF protection."""

    state: str = Field(..., description="Random state string for CSRF protection")
    redirect_url: Optional[str] = Field(None, description="URL to redirect after OAuth flow")


class OAuthCallback(BaseModel):
    """OAuth callback request."""

    code: str = Field(..., description="Authorization code from GitHub")
    state: str = Field(..., description="State parameter for CSRF verification")


class AuthResponse(BaseModel):
    """Authentication response with user info and tokens."""

    user_id: str
    login: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class GitHubUserInfo(BaseModel):
    """GitHub user information from OAuth flow."""

    id: int = Field(..., description="GitHub user ID")
    login: str = Field(..., description="GitHub username")
    name: Optional[str] = Field(None, description="Display name")
    email: Optional[str] = Field(None, description="Email address")
    avatar_url: str = Field(..., description="Avatar URL")