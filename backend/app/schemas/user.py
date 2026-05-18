"""
User Schemas
Request/Response models for user management.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr, field_validator


class UserBase(BaseModel):
    """Base user schema with common fields."""

    email: Optional[EmailStr] = Field(None, description="Email address")
    name: Optional[str] = Field(None, max_length=255, description="Display name")


class UserCreate(UserBase):
    """Schema for creating a new user."""

    github_id: int = Field(..., description="GitHub user ID")
    login: str = Field(..., max_length=255, description="GitHub username")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")


class UserUpdate(BaseModel):
    """Schema for updating user information."""

    email: Optional[EmailStr] = Field(None, description="Email address")
    name: Optional[str] = Field(None, max_length=255, description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")


class UserResponse(BaseModel):
    """User response schema."""

    id: str = Field(..., description="User UUID")
    github_id: int = Field(..., description="GitHub user ID")
    login: str = Field(..., description="GitHub username")
    email: Optional[str] = Field(None, description="Email address")
    name: Optional[str] = Field(None, description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")
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
    github_id: int
    login: str
    email: Optional[str]
    name: Optional[str]
    avatar_url: Optional[str]
    is_active: bool

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v