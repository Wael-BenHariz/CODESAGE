"""Invitation schemas (plan Step 11 + repo-scoped grants).

``InvitationCreate.role`` only ever holds the two *invitable* roles —
ORG_ADMIN and PLATFORM_ADMIN can never be granted by an invitation, so
anything else is a 422 at the schema layer (before rate limiting, storage
or mail). Nothing here can carry the raw token: it exists only inside the
emailed link.

Repo-scoped variant: one role for a whole selection of repositories
(``repository_ids``), validated against the org's installation by the
route (400 before anything is persisted). An empty/absent selection keeps
the original org-only invitation behaviour.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class InvitationCreate(BaseModel):
    """POST /orgs/{org_id}/invitations body."""

    email: EmailStr
    role: Literal["DEVELOPER", "REVIEWER"]
    # One role applies to every selected repository (cap + dedupe here;
    # org membership of each id is checked in the route → 400).
    repository_ids: list[UUID] = Field(
        default_factory=list,
        max_length=100,
        description="repositories.id rows to grant with `role` ([] = org-only)",
    )

    @field_validator("repository_ids", mode="before")
    @classmethod
    def _dedupe_preserving_order(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        seen: set = set()
        deduped = []
        for item in value:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped


class InvitationOut(BaseModel):
    """One invitation as the org's admins see it — never the raw token."""

    id: UUID
    email: str
    role: str
    status: str  # pending | accepted | revoked | expired
    expires_at: datetime
    created_at: datetime
    invited_by: str | None = None  # inviter's login
    repository_ids: list[UUID] = []  # granted repositories (uuids)
    repositories: list[str] = []  # ...resolved to owner/repo for display
    github_error: str | None = None  # collaborator pass summary (NULL = ok)


class InvitationPreview(BaseModel):
    """Public GET /invitations/{token} — org, role, masked address."""

    org_name: str
    role: str
    email_masked: str
    repositories: list[str] = []  # what the link grants (owner/repo names)


class InvitationAcceptResult(BaseModel):
    """POST /invitations/{token}/accept."""

    org_id: UUID
    org_name: str
    role: str  # resulting org_members role (never-downgraded on conflict)
    email_mismatch: bool
    github_error: str | None = None  # collaborator failures (NULL = none)
