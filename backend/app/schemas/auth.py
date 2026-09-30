"""
Authentication Schemas
Request/Response models for OAuth and JWT authentication.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Token(BaseModel):
    """JWT access token response."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration in seconds")
    refresh_token: str | None = Field(
        None, description="Refresh token for token renewal"
    )


class TokenPayload(BaseModel):
    """JWT token payload content."""

    sub: str = Field(..., description="Subject (user ID)")
    exp: datetime = Field(..., description="Expiration timestamp")
    iat: datetime = Field(..., description="Issued at timestamp")
    type: str = Field(default="access", description="Token type: access or refresh")


class RefreshRequest(BaseModel):
    """Refresh-token exchange request (JSON body only, no query params)."""

    refresh_token: str = Field(
        ..., min_length=1, description="JWT refresh token to exchange"
    )


class LogoutRequest(BaseModel):
    """Optional logout body: a refresh token proves identity on its own."""

    refresh_token: str | None = Field(
        None, description="JWT refresh token identifying the user to log out"
    )


class OAuthState(BaseModel):
    """OAuth state parameter for CSRF protection."""

    state: str = Field(..., description="Random state string for CSRF protection")
    redirect_url: str | None = Field(
        None, description="URL to redirect after OAuth flow"
    )


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
    name: str | None = Field(None, description="Display name")
    email: str | None = Field(None, description="Email address")
    avatar_url: str = Field(..., description="Avatar URL")
