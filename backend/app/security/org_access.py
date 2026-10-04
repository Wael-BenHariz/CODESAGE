"""Org-scoped authorization — the plan §2 capability model as a dependency.

Every org-scoped endpoint guards in this exact order:

1. **NONE on a write endpoint → 403 immediately** — unconditionally
   read-only; membership cannot rescue it.
2. **Membership**: the caller must hold an ``org_members`` row for the
   resource's org — otherwise **404** (uniform detail: cross-org callers
   must not learn whether the org exists). ``PLATFORM_ADMIN`` bypasses
   this step only when ``platform_admin_bypass=True`` — reads and
   settings endpoints (flag F2). Mutating review actions (dismiss,
   restore, summary edit, post, validate — Steps 7/9) pass
   ``platform_admin_bypass=False`` so a platform admin can never post to
   a customer's GitHub PR without being an org member.
3. **Effective role** = ``max(JWT role, org_members.role)``; when below
   the endpoint's required role → **403**.

Reading-order consequence: cross-org yields 404 *before* any role 403 for
DEVELOPER+ callers, while NONE hits step 1 first on writes — satisfying
both contract tests ("no org_members row → 404 regardless of role",
"NONE → 403 on every write endpoint").
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import Org, OrgMember, User
from app.security.dependencies import get_current_user
from app.security.roles import (
    ROLE_DEVELOPER,
    ROLE_NONE,
    ROLE_ORG_ADMIN,
    ROLE_PLATFORM_ADMIN,
    ROLE_REVIEWER,
)

logger = logging.getLogger(__name__)

# Ladder rank (plan §2). NONE has no ladder position — ranked lowest so
# max(NONE, member role) resolves to the member role; step 1 already
# blocks NONE from every write regardless.
_RANK = {
    ROLE_NONE: 0,
    ROLE_DEVELOPER: 1,
    ROLE_REVIEWER: 2,
    ROLE_ORG_ADMIN: 3,
    ROLE_PLATFORM_ADMIN: 4,
}

_LADDER_ROLES = (ROLE_DEVELOPER, ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN)


@dataclass(frozen=True)
class OrgAccess:
    """Result of a successful org guard — carry into the handler."""

    user: User
    org: Org
    membership: OrgMember | None
    effective_role: str  # max(JWT, org role); None-membership (PLATFORM_ADMIN) = JWT


def _not_found() -> HTTPException:
    # One detail string for "no such org" AND "not a member": a cross-org
    # caller must not learn that the org exists.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Organization not found",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


def require_org_role(
    min_role: str,
    *,
    write: bool,
    platform_admin_bypass: bool = True,
):
    """Dependency factory for org-scoped routes (plan §2).

    Args:
        min_role: minimum *effective* role (a ladder role, never NONE).
        write: True for mutating endpoints — step 1 then rejects NONE
            with 403 before any membership lookup.
        platform_admin_bypass: whether PLATFORM_ADMIN may pass step 2
            without an org_members row (reads/settings: True; mutating
            review actions: False — flag F2).
    """
    if min_role not in _LADDER_ROLES:
        raise ValueError(f"require_org_role needs a ladder role, got {min_role!r}")

    async def dependency(
        org_id: UUID = Path(...),  # noqa: B008 — resolved from the route path
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: User = Depends(get_current_user),  # noqa: B008
    ) -> OrgAccess:
        # Step 1: NONE is unconditionally read-only on writes.
        if write and current_user.role == ROLE_NONE:
            raise _forbidden()

        # Step 2: org existence and membership (uniform 404).
        org_result = await db.execute(select(Org).where(Org.id == org_id))
        org_row = org_result.scalar_one_or_none()
        if org_row is None:
            raise _not_found()

        member_result = await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == current_user.id,
            )
        )
        membership = member_result.scalar_one_or_none()
        if membership is None and not (
            platform_admin_bypass and current_user.role == ROLE_PLATFORM_ADMIN
        ):
            raise _not_found()

        # Step 3: effective role = max(JWT, org role).
        jwt_role = current_user.role if current_user.role in _RANK else ROLE_NONE
        member_role = (
            membership.role
            if membership is not None and membership.role in _RANK
            else ROLE_NONE
        )
        effective = jwt_role if _RANK[jwt_role] >= _RANK[member_role] else member_role
        if _RANK[effective] < _RANK[min_role]:
            raise _forbidden()

        return OrgAccess(
            user=current_user,
            org=org_row,
            membership=membership,
            effective_role=effective,
        )

    return dependency
