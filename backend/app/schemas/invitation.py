"""Invitation schemas (plan Step 11).

``InvitationCreate.role`` only ever holds the two *invitable* roles —
ORG_ADMIN and PLATFORM_ADMIN can never be granted by an invitation, so
anything else is a 422 at the schema layer (before rate limiting, storage
or mail). Nothing here can carry the raw token: it exists only inside the
emailed link.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class InvitationCreate(BaseModel):
    """POST /orgs/{org_id}/invitations body."""

    email: EmailStr
    role: Literal["DEVELOPER", "REVIEWER"]


class InvitationOut(BaseModel):
    """One invitation as the org's admins see it — never the raw token."""

    id: UUID
    email: str
    role: str
    status: str  # pending | accepted | revoked | expired
    expires_at: datetime
    created_at: datetime
    invited_by: str | None = None  # inviter's login


class InvitationPreview(BaseModel):
    """Public GET /invitations/{token} — org, role, masked address."""

    org_name: str
    role: str
    email_masked: str


class InvitationAcceptResult(BaseModel):
    """POST /invitations/{token}/accept."""

    org_id: UUID
    org_name: str
    role: str  # resulting org_members role (never-downgraded on conflict)
    email_mismatch: bool
