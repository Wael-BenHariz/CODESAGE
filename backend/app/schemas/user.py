"""
User Schemas
Request/Response models for user management.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserBase(BaseModel):
    """Base user schema with common fields."""

    email: EmailStr | None = Field(None, description="Email address")
    name: str | None = Field(None, max_length=255, description="Display name")


class UserCreate(UserBase):
    """Schema for creating a new user."""

    github_id: int = Field(..., description="GitHub user ID")
    login: str = Field(..., max_length=255, description="GitHub username")
    avatar_url: str | None = Field(None, description="Avatar URL")


class UserUpdate(BaseModel):
    """Schema for updating user information."""

    email: EmailStr | None = Field(None, description="Email address")
    name: str | None = Field(None, max_length=255, description="Display name")
    avatar_url: str | None = Field(None, description="Avatar URL")


class UserResponse(BaseModel):
    """User response schema."""

    id: str = Field(..., description="User UUID")
    keycloak_id: str | None = Field(None, description="Keycloak subject (sub)")
    role: str = Field(
        "DEVELOPER", description="Realm role: SUPER_ADMIN | DEVELOPER | GUEST"
    )
    github_id: int | None = Field(None, description="GitHub user ID")
    login: str = Field(..., description="GitHub username")
    email: str | None = Field(None, description="Email address")
    name: str | None = Field(None, description="Display name")
    avatar_url: str | None = Field(None, description="Avatar URL")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v


class UserListResponse(BaseModel):
    """Paginated list of users."""

    items: list[UserResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total count")
    page: int = Field(..., description="Current page")
    per_page: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total pages")


class CurrentUser(BaseModel):
    """Current authenticated user information."""

    id: str
    github_id: int | None
    role: str = "DEVELOPER"
    login: str
    email: str | None
    name: str | None
    avatar_url: str | None
    is_active: bool

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v
