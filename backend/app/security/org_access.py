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
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    PullRequest,
    Repository,
    Review,
    User,
)
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


@dataclass(frozen=True)
class ReviewAccess:
    """Result of a successful review guard — carry into the handler.

    The review is resolved in the same guard so handlers never re-query
    it (and can never observe a different row than the one authorized).
    """

    user: User
    review: Review
    org: Org
    membership: OrgMember | None
    effective_role: str


def _not_found() -> HTTPException:
    # One detail string for "no such org" AND "not a member": a cross-org
    # caller must not learn that the org exists.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Organization not found",
    )


def _review_not_found() -> HTTPException:
    # Same detail for "no such review", "no org row" and "not a member":
    # a cross-org caller must not learn that the review exists.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Review not found",
    )


def _pull_request_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Pull request not found",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


def _effective_role(jwt_role: str, membership: OrgMember | None) -> str:
    """Plan §2 step 3: ``max(JWT role, org_members.role)``."""
    jwt = jwt_role if jwt_role in _RANK else ROLE_NONE
    member = (
        membership.role
        if membership is not None and membership.role in _RANK
        else ROLE_NONE
    )
    return jwt if _RANK[jwt] >= _RANK[member] else member


async def _resolve_org_and_membership(
    db: AsyncSession,
    pull_request_id: UUID,
    user: User,
    *,
    not_found,
) -> tuple[Org, OrgMember | None]:
    """Chain ``pull request -> repo -> installation -> org`` + caller's row.

    Raises ``not_found()`` when the chain or the org row is missing
    (unwatched/never-provisioned repo — indistinguishable from cross-org
    on purpose). A missing membership is returned as ``None``: the caller
    decides between the F2 PLATFORM_ADMIN bypass and a uniform 404.
    """
    chain = await db.execute(
        select(GitHubInstallation.installation_id)
        .join(Repository, Repository.installation_id == GitHubInstallation.id)
        .join(PullRequest, PullRequest.repository_id == Repository.id)
        .where(PullRequest.id == pull_request_id)
    )
    installation_id = chain.scalar_one_or_none()
    if installation_id is None:
        raise not_found()

    org_result = await db.execute(
        select(Org).where(Org.installation_id == installation_id)
    )
    org_row = org_result.scalar_one_or_none()
    if org_row is None:
        raise not_found()

    member_result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_row.id,
            OrgMember.user_id == user.id,
        )
    )
    return org_row, member_result.scalar_one_or_none()


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


def require_review_access(
    min_role: str,
    *,
    write: bool,
    platform_admin_bypass: bool = True,
):
    """Dependency factory for review-scoped routes (plan §2, Step 7).

    Same three steps as :func:`require_org_role`, with the resource's org
    resolved through ``review -> pull request -> repo -> installation ->
    org``. Unknown review, missing org row and cross-org all raise the
    *same* "Review not found" 404.

    Args:
        min_role: minimum *effective* role (a ladder role, never NONE).
        write: True for mutating endpoints — step 1 rejects NONE with 403
            before any lookup.
        platform_admin_bypass: whether PLATFORM_ADMIN may pass membership
            without an org_members row. Reads: True (F2). The mutating
            staged-posting actions (summary edit, dismiss, restore, post)
            pass False — a platform admin cannot post to a customer's PR
            without being an org member (F2 carve-out).
    """
    if min_role not in _LADDER_ROLES:
        raise ValueError(f"require_review_access needs a ladder role, got {min_role!r}")

    async def dependency(
        review_id: str = Path(...),
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: User = Depends(get_current_user),  # noqa: B008
    ) -> ReviewAccess:
        # Step 1: NONE is unconditionally read-only on writes.
        if write and current_user.role == ROLE_NONE:
            raise _forbidden()

        try:
            review_uuid = UUID(review_id)
        except (ValueError, TypeError):
            raise _review_not_found() from None
        review_result = await db.execute(select(Review).where(Review.id == review_uuid))
        review = review_result.scalar_one_or_none()
        if review is None:
            raise _review_not_found()

        # Step 2: org row + membership (uniform 404, F2 bypass optional).
        # Coerce the ORM attr (sqlalchemy UUID type) to uuid.UUID — mypy
        # sees the dialect type here, and str() round-trips either way.
        org_row, membership = await _resolve_org_and_membership(
            db,
            UUID(str(review.pull_request_id)),
            current_user,
            not_found=_review_not_found,
        )
        if membership is None and not (
            platform_admin_bypass and current_user.role == ROLE_PLATFORM_ADMIN
        ):
            raise _review_not_found()

        # Step 3: effective role floor.
        effective = _effective_role(current_user.role, membership)
        if _RANK[effective] < _RANK[min_role]:
            raise _forbidden()

        return ReviewAccess(
            user=current_user,
            review=review,
            org=org_row,
            membership=membership,
            effective_role=effective,
        )

    return dependency


def require_pull_request_access(
    min_role: str,
    *,
    write: bool,
    platform_admin_bypass: bool = True,
):
    """Dependency factory for pull-request-scoped routes (plan §2, F3).

    Same capability model as :func:`require_review_access` but keyed by
    ``pull_request_id`` — for ``GET /pull-requests/{id}``, its ``/reviews``
    list and ``POST /pull-requests/{id}/review``. Returns the org context
    (handlers already load the pull request themselves).
    """
    if min_role not in _LADDER_ROLES:
        raise ValueError(
            f"require_pull_request_access needs a ladder role, got {min_role!r}"
        )

    async def dependency(
        pull_request_id: str = Path(...),
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: User = Depends(get_current_user),  # noqa: B008
    ) -> OrgAccess:
        if write and current_user.role == ROLE_NONE:
            raise _forbidden()

        try:
            pull_request_uuid = UUID(pull_request_id)
        except (ValueError, TypeError):
            raise _pull_request_not_found() from None

        org_row, membership = await _resolve_org_and_membership(
            db,
            pull_request_uuid,
            current_user,
            not_found=_pull_request_not_found,
        )
        if membership is None and not (
            platform_admin_bypass and current_user.role == ROLE_PLATFORM_ADMIN
        ):
            raise _pull_request_not_found()

        effective = _effective_role(current_user.role, membership)
        if _RANK[effective] < _RANK[min_role]:
            raise _forbidden()

        return OrgAccess(
            user=current_user,
            org=org_row,
            membership=membership,
            effective_role=effective,
        )

    return dependency
