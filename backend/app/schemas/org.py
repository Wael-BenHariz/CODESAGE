"""Organization listing schemas (Step 5 — org context for the UI).

``GET /orgs`` returns the organizations a caller may act in: members see
their own memberships (with their ``org_members`` role), PLATFORM_ADMIN
sees every org (flag F2 read/settings bypass) with ``role`` set only when
they also hold a membership row.
"""

from uuid import UUID

from pydantic import BaseModel


class OrgSummary(BaseModel):
    """One organization the caller can select as their org context."""

    id: UUID
    name: str
    account_type: str  # 'User' | 'Organization'
    # The caller's own org_members role; None for platform admins without
    # a membership row (their effective role is PLATFORM_ADMIN anyway).
    role: str | None = None
