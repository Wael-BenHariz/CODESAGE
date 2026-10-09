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
        "NONE",
        description=(
            "Realm role: PLATFORM_ADMIN | ORG_ADMIN | REVIEWER | DEVELOPER | NONE"
        ),
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


class WorkspaceSummary(BaseModel):
    """One workspace as seen in ``GET /auth/me``.

    ``role`` is the *effective* role (ladder max of realm role and
    membership) and ``capabilities`` the permission flags for that role —
    the frontend renders from those instead of re-deriving role lists.
    """

    id: str = Field(..., description="Workspace UUID")
    name: str = Field(..., description="Workspace name")
    type: str = Field(..., description="PERSONAL | ORG")
    role: str = Field(..., description="Effective role in this workspace")
    capabilities: dict[str, bool] = Field(
        ..., description="Permission flags (view/trigger/request/review/...)"
    )
    is_personal: bool = Field(False, description="Type == PERSONAL")


class MeResponse(UserResponse):
    """``GET /auth/me`` payload: the user row plus workspace contexts.

    ``capabilities`` mirrors the flags of the *global* realm role (used for
    platform-level UI); ``workspaces`` carries per-workspace roles and
    flags. Empty lists are legal — a brokered login with no membership
    still authenticates (role NONE, no workspace access).
    """

    workspaces: list[WorkspaceSummary] = Field(
        default_factory=list, description="Workspaces the user belongs to"
    )
    capabilities: dict[str, bool] = Field(
        default_factory=dict, description="Flags for the global realm role"
    )


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
