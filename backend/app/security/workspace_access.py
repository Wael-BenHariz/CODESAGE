"""Workspace-scoped authorization — single source of truth for the RBAC matrix.

This module owns the capability model defined in ``docs/rbac-target-design.md``
§2.3–§2.5. Nothing else in the app may hard-code a role list; every endpoint
asks this module for a *permission* (``"trigger"``, ``"repo_config"``, …).

Permission lists (target design §2.3)
-------------------------------------
    VIEW_ROLES       = NONE, DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
    TRIGGER_ROLES    = DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
    REQUEST_ROLES    = DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
    REVIEW_ROLES     = REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
    REPO_CONFIG_ROLES= REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
    REPO_ADMIN_ROLES = ORG_ADMIN, PLATFORM_ADMIN
    PLATFORM_ROLES   = PLATFORM_ADMIN

Precedence (§2.2)::

    PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE

Check order for a guarded endpoint (mirrors ``org_access`` so the two models
never disagree):

1. **Resolve the workspace** — explicit ``workspace_id`` path param, else the
   request's resource (repository / pull request / review / comment /
   installation → its ``workspace_id``, falling back through the
   installation → org → workspace chain), else an optional ``X-Workspace-Id``
   header. ``None`` means "no workspace context" (legacy or unbound data).
2. **No workspace context** → fall back to the *global* JWT role against the
   permission's lowest allowed role. This is the pre-workspace behaviour, so
   unbound data never becomes stricter than before *and* never looser.
3. **Workspace context** → the caller must hold a membership row (a
   ``workspace_members`` row, or an ``org_members`` row for the org linked to
   that workspace — both tables are kept in sync by the 020 backfill and read
   together here so the two never drift). Non-members get a uniform **404**
   (existence must not leak); ``PLATFORM_ADMIN`` bypasses this step.
4. **Effective role** = ``max(JWT role, membership role)`` on the ladder;
   below the permission's lowest allowed role → **403**.

Consequences worth stating out loud:

* a GitHub-broker user (global ``NONE``) is ``ORG_ADMIN`` of their own
  personal workspace, so they can connect repos there — membership rescues
  the realm role (this is why ``NONE`` is ranked *lowest*, not above
  ``ORG_ADMIN``);
* an explicit read-only downgrade cannot be silently undone by a platform
  admin bypass on workspace endpoints — the ladder check still applies to the
  effective role, and ``NONE`` never reaches a write permission.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    PullRequest,
    Repository,
    Review,
    ReviewComment,
    User,
    Workspace,
    WorkspaceMember,
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

# ---------------------------------------------------------------------------
# Permission lists (target design §2.3) — the single source of truth.
# ---------------------------------------------------------------------------

VIEW_ROLES = [
    ROLE_NONE,
    ROLE_DEVELOPER,
    ROLE_REVIEWER,
    ROLE_ORG_ADMIN,
    ROLE_PLATFORM_ADMIN,
]
TRIGGER_ROLES = [ROLE_DEVELOPER, ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REQUEST_ROLES = [ROLE_DEVELOPER, ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REVIEW_ROLES = [ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REPO_CONFIG_ROLES = [ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
REPO_ADMIN_ROLES = [ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN]
PLATFORM_ROLES = [ROLE_PLATFORM_ADMIN]

#: permission name -> every role allowed to perform it.
PERMISSION_MAP: dict[str, list[str]] = {
    "view": VIEW_ROLES,
    "trigger": TRIGGER_ROLES,
    "request": REQUEST_ROLES,
    "review": REVIEW_ROLES,
    "repo_config": REPO_CONFIG_ROLES,
    "repo_admin": REPO_ADMIN_ROLES,
    "platform": PLATFORM_ROLES,
}

# ---------------------------------------------------------------------------
# Ladder (§2.2). NONE is the read-only sentinel and ranks *lowest* — the old
# bug placed it above ORG_ADMIN, which let an unrecognised claim outrank an
# org admin. Fixed here and mirrored by roles.derive_role.
# ---------------------------------------------------------------------------

RANK: dict[str, int] = {
    ROLE_NONE: 0,
    ROLE_DEVELOPER: 1,
    ROLE_REVIEWER: 2,
    ROLE_ORG_ADMIN: 3,
    ROLE_PLATFORM_ADMIN: 4,
}

#: Roles that carry a real ladder position (i.e. can be a minimum requirement).
LADDER_ROLES = (ROLE_DEVELOPER, ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN)

#: permission -> the *lowest* role that satisfies it (the threshold).
_MIN_ROLE: dict[str, str] = {
    name: min(roles, key=lambda r: RANK[r]) for name, roles in PERMISSION_MAP.items()
}


def min_role_for(permission: str) -> str:
    """Lowest role satisfying ``permission`` (raises on an unknown name)."""
    try:
        return _MIN_ROLE[permission]
    except KeyError:  # pragma: no cover - programming error, fail fast at import
        raise ValueError(
            f"unknown permission {permission!r}; expected one of {sorted(PERMISSION_MAP)}"
        ) from None


def effective_role(jwt_role: str, membership_role: str | None) -> str:
    """Ladder max of the realm role and the per-workspace membership role."""
    jwt_rank = RANK.get(jwt_role, RANK[ROLE_NONE])
    member_rank = RANK.get(membership_role or ROLE_NONE, RANK[ROLE_NONE])
    if member_rank > jwt_rank:
        return membership_role or ROLE_NONE
    return jwt_role if jwt_role in RANK else ROLE_NONE


def allowed(permission: str, role: str) -> bool:
    """Is ``role`` allowed to perform ``permission``? (No DB — pure matrix.)"""
    return RANK.get(role, RANK[ROLE_NONE]) >= RANK[min_role_for(permission)]


def capability_flags(role: str) -> dict[str, bool]:
    """Per-workspace capability flags for ``GET /auth/me`` payloads.

    The frontend renders from these instead of re-deriving role lists, so a
    rule change lands in exactly one place (this function).
    """
    return {
        "view": allowed("view", role),
        "trigger": allowed("trigger", role),
        "request": allowed("request", role),
        "review": allowed("review", role),
        "repo_config": allowed("repo_config", role),
        "repo_admin": allowed("repo_admin", role),
        "platform": allowed("platform", role),
    }


def _forbidden() -> HTTPException:
    """403 with a generic detail — never leak which roles exist."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
    )


def _not_found() -> HTTPException:
    """404 with a uniform detail — cross-workspace callers learn nothing."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
    )


# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceContext:
    """Everything a guarded endpoint needs to know about the caller."""

    user: User
    workspace: Workspace | None
    workspace_id: UUID | None
    membership_role: str | None
    effective_role: str

    @property
    def is_member(self) -> bool:
        return self.membership_role is not None

    @property
    def is_platform_admin(self) -> bool:
        return self.effective_role == ROLE_PLATFORM_ADMIN

    def can(self, permission: str) -> bool:
        """Matrix check against the effective role (no DB round trip)."""
        return allowed(permission, self.effective_role)


async def membership_role(
    db: AsyncSession, user_id: UUID, workspace: Workspace
) -> str | None:
    """Role of ``user_id`` in ``workspace`` (public — route modules use it to
    inspect *another* member's role, e.g. the last-admin guard).

    Reads **both** membership tables and takes the ladder max:
    ``workspace_members`` (the new source of truth) plus ``org_members`` for
    the org linked to this workspace (the legacy table the 020 backfill
    seeded from). Reading both makes the tables drift-proof — an invitation
    that writes only one of them can never lock a member out.
    """
    best: str | None = None

    row = await db.execute(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user_id,
        )
    )
    best = row.scalar_one_or_none()

    # A PERSONAL workspace is owned by exactly one user who is its ORG_ADMIN
    # by definition (target design §2.1) — the 020 backfill created those
    # workspaces without membership rows, so the owner claim is authoritative
    # whenever no explicit row exists.
    if best is None and workspace.owner_user_id == user_id:
        return ROLE_ORG_ADMIN

    org_row = await db.execute(
        select(OrgMember.role)
        .join(Org, Org.id == OrgMember.org_id)
        .where(Org.workspace_id == workspace.id, OrgMember.user_id == user_id)
    )
    org_role = org_row.scalar_one_or_none()
    if org_role is not None and (
        best is None or RANK.get(org_role, 0) > RANK.get(best, 0)
    ):
        best = org_role

    return best


async def ensure_personal_workspace(db: AsyncSession, user: User) -> Workspace:
    """Idempotently create the caller's PERSONAL workspace (target design §2.1).

    Runs on first login (including the first GitHub-broker login). The owner
    gets an explicit ``ORG_ADMIN`` membership row so membership queries,
    ``GET /workspaces`` and the resolver all agree without special cases.
    """
    result = await db.execute(
        select(Workspace).where(
            Workspace.type == "PERSONAL", Workspace.owner_user_id == user.id
        )
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        workspace = Workspace(
            type="PERSONAL",
            name=f"{user.login}'s workspace",
            owner_user_id=user.id,
        )
        db.add(workspace)
        await db.flush()

    member = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        db.add(
            WorkspaceMember(
                workspace_id=workspace.id, user_id=user.id, role=ROLE_ORG_ADMIN
            )
        )
        await db.flush()
    elif member.role not in RANK:
        member.role = ROLE_ORG_ADMIN
        await db.flush()

    return workspace


async def list_user_workspaces(
    db: AsyncSession, user: User
) -> list[tuple[Workspace, str]]:
    """Every workspace the caller can act in, with their *effective* role.

    Sources, merged by ladder max (drift-proof, see :func:`membership_role`):
    the personal workspace (owner), ``workspace_members`` rows and
    ``org_members`` rows of orgs linked to a workspace. The realm role is
    folded in so the returned role equals what enforcement will compute.
    """
    entries: dict[UUID, tuple[Workspace, str]] = {}

    def put(workspace: Workspace, membership_role: str | None) -> None:
        role = effective_role(user.role, membership_role)
        current = entries.get(workspace.id)
        if current is None:
            entries[workspace.id] = (workspace, role)
        else:
            entries[workspace.id] = (
                workspace,
                effective_role(current[1], role),
            )

    personal = (
        await db.execute(
            select(Workspace).where(
                Workspace.type == "PERSONAL", Workspace.owner_user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if personal is not None:
        put(personal, ROLE_ORG_ADMIN)

    for workspace, role in (
        await db.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user.id)
        )
    ).all():
        put(workspace, role)

    for workspace, role in (
        await db.execute(
            select(Workspace, OrgMember.role)
            .join(Org, Org.workspace_id == Workspace.id)
            .join(OrgMember, OrgMember.org_id == Org.id)
            .where(OrgMember.user_id == user.id)
        )
    ).all():
        put(workspace, role)

    return sorted(
        entries.values(),
        key=lambda item: (item[0].type != "PERSONAL", item[0].name.lower()),
    )


async def sync_membership_role(
    db: AsyncSession, workspace: Workspace, user_id: UUID, role: str
) -> None:
    """Write a member's role to ``workspace_members`` **and** ``org_members``.

    Authorization reads both tables and takes the ladder max, so a role
    change must land in both — otherwise a demotion in one table would be
    cancelled out by the stale row in the other.

    ``org_members`` cannot store ``NONE`` (its check constraint is
    DEVELOPER/REVIEWER/ORG_ADMIN) — an explicit read-only downgrade is
    expressed by *removing* the org row and keeping ``NONE`` in
    ``workspace_members``.
    """
    if role not in RANK or role == ROLE_PLATFORM_ADMIN:
        raise ValueError(f"not a membership role: {role!r}")

    row = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user_id, role=role))
    elif row.role != role:
        row.role = role

    if workspace.type != "ORG":
        await db.flush()
        return

    org = (
        await db.execute(select(Org).where(Org.workspace_id == workspace.id))
    ).scalar_one_or_none()
    if org is None:
        await db.flush()
        return

    org_row = (
        await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == org.id, OrgMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    if role == ROLE_NONE:
        if org_row is not None:
            await db.delete(org_row)
    elif org_row is None:
        db.add(OrgMember(org_id=org.id, user_id=user_id, role=role))
    elif org_row.role != role:
        org_row.role = role

    await db.flush()


async def remove_membership(
    db: AsyncSession, workspace: Workspace, user_id: UUID
) -> None:
    """Delete a member from both membership tables."""
    await db.execute(
        delete(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if workspace.type == "ORG":
        org = (
            await db.execute(select(Org).where(Org.workspace_id == workspace.id))
        ).scalar_one_or_none()
        if org is not None:
            await db.execute(
                delete(OrgMember).where(
                    OrgMember.org_id == org.id, OrgMember.user_id == user_id
                )
            )
    await db.flush()


async def _workspace_for_resource(db: AsyncSession, request: Request) -> UUID | None:
    """Derive the workspace from the endpoint's resource, if it has one.

    Recognised path params: ``workspace_id`` (direct), ``repository_id``,
    ``pull_request_id``, ``review_id``, ``review_comment_id`` / ``comment_id``,
    ``installation_id``. Recognised query params: ``installation_id``.

    Returns ``None`` when no resource is present or the resource is unbound
    (``workspace_id IS NULL``) — the caller then falls back to the global role.
    """
    params = request.path_params
    query = request.query_params

    if "workspace_id" in params:
        return _as_uuid(params["workspace_id"])

    if "repository_id" in params:
        repo_id = _as_uuid(params["repository_id"])
        if repo_id is None:
            return None
        return (
            await db.execute(
                select(Repository.workspace_id).where(Repository.id == repo_id)
            )
        ).scalar_one_or_none()

    if "pull_request_id" in params:
        pr_id = _as_uuid(params["pull_request_id"])
        if pr_id is None:
            return None
        return (
            await db.execute(
                select(PullRequest.workspace_id).where(PullRequest.id == pr_id)
            )
        ).scalar_one_or_none()

    if "review_id" in params:
        review_id = _as_uuid(params["review_id"])
        if review_id is None:
            return None
        return (
            await db.execute(select(Review.workspace_id).where(Review.id == review_id))
        ).scalar_one_or_none()

    if "review_comment_id" in params or "comment_id" in params:
        comment_id = _as_uuid(
            params.get("review_comment_id") or params.get("comment_id")
        )
        if comment_id is None:
            return None
        # ReviewComment has no workspace_id of its own — go through its review.
        return (
            await db.execute(
                select(Review.workspace_id)
                .join(ReviewComment, ReviewComment.review_id == Review.id)
                .where(ReviewComment.id == comment_id)
            )
        ).scalar_one_or_none()

    if "installation_id" in params or "installation_id" in query:
        raw = params.get("installation_id") or query.get("installation_id")
        return await _workspace_for_installation_id(db, raw)

    return None


async def _workspace_for_installation_id(
    db: AsyncSession, raw: str | None
) -> UUID | None:
    if raw is None:
        return None
    try:
        installation_id = int(raw)
    except (TypeError, ValueError):
        return None
    row = await db.execute(
        select(GitHubInstallation.workspace_id).where(
            GitHubInstallation.installation_id == installation_id
        )
    )
    ws_id = row.scalar_one_or_none()
    if ws_id is not None:
        return ws_id
    return None


def _as_uuid(raw: str | None) -> UUID | None:
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


async def _context_for_workspace(
    db: AsyncSession, user: User, workspace: Workspace
) -> WorkspaceContext:
    """Build the caller's context for a known workspace (membership enforced)."""
    member_role = await membership_role(db, user.id, workspace)
    if member_role is None:
        # Cross-workspace callers must not learn the workspace exists;
        # a platform admin reads/acts everywhere (F2-style bypass).
        if (user.role if user.role in RANK else ROLE_NONE) == ROLE_PLATFORM_ADMIN:
            member_role = ROLE_PLATFORM_ADMIN
        else:
            raise _not_found()

    return WorkspaceContext(
        user=user,
        workspace=workspace,
        workspace_id=workspace.id,
        membership_role=member_role,
        effective_role=effective_role(user.role, member_role),
    )


async def check_permission_in_workspace(
    db: AsyncSession, user: User, workspace_id: UUID, permission: str
) -> WorkspaceContext:
    """Check ``permission`` in an **explicitly known** workspace.

    For handlers whose resource→workspace traversal they already performed
    themselves (e.g. comment → review → workspace). Identical semantics to
    :func:`require_workspace_permission`: unknown workspace / non-member → 404,
    effective role below the threshold → 403.
    """
    min_role_for(permission)  # fail fast on a typo'd permission name

    workspace = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    if workspace is None:
        raise _not_found()

    ctx = await _context_for_workspace(db, user, workspace)
    if not ctx.can(permission):
        raise _forbidden()
    return ctx


async def resolve_workspace_context(
    db: AsyncSession, request: Request, user: User
) -> WorkspaceContext:
    """Resolve the caller's workspace + effective role for this request."""
    ws_id = await _workspace_for_resource(db, request)
    if ws_id is None:
        header = request.headers.get("X-Workspace-Id")
        ws_id = _as_uuid(header)

    if ws_id is None:
        # No workspace context → global role only (pre-workspace behaviour).
        role = user.role if user.role in RANK else ROLE_NONE
        return WorkspaceContext(
            user=user,
            workspace=None,
            workspace_id=None,
            membership_role=None,
            effective_role=role,
        )

    workspace = (
        await db.execute(select(Workspace).where(Workspace.id == ws_id))
    ).scalar_one_or_none()
    if workspace is None:
        # An unknown workspace id is either a typo or a probe — uniform 404.
        raise _not_found()

    return await _context_for_workspace(db, user, workspace)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def require_workspace_permission(permission: str) -> Callable[..., Awaitable]:
    """FastAPI dependency enforcing ``permission`` for this request's workspace.

    Usage::

        ctx: WorkspaceContext = Depends(require_workspace_permission("repo_config"))

    Raises 404 for non-members of the resolved workspace and 403 when the
    effective role is below the permission's threshold. Without a workspace
    context only the global JWT role is consulted.
    """
    min_role_for(permission)  # validate at import time, not request time

    async def dependency(
        request: Request,
        db: AsyncSession = Depends(get_db),  # noqa: B008
        current_user: User = Depends(get_current_user),  # noqa: B008
    ) -> WorkspaceContext:
        ctx = await resolve_workspace_context(db, request, current_user)
        if not ctx.can(permission):
            raise _forbidden()
        return ctx

    dependency.__name__ = f"require_{permission}"
    return dependency


async def check_workspace_permission(
    db: AsyncSession,
    request: Request,
    user: User,
    permission: str,
) -> WorkspaceContext:
    """Imperative variant for checks made *inside* a handler.

    Identical semantics to :func:`require_workspace_permission`; used where
    the check depends on data only the handler has loaded.
    """
    ctx = await resolve_workspace_context(db, request, user)
    if not ctx.can(permission):
        raise _forbidden()
    return ctx


def require_workspace(ctx: WorkspaceContext) -> Workspace:
    """The resolved workspace of a workspace-scoped route (uniform 404).

    Handlers guarded by :func:`require_workspace_permission` whose URL carries
    a ``workspace_id`` must operate *inside* a workspace — a malformed or
    missing workspace context is a 404, never a 500 from dereferencing
    ``None``. Use this instead of touching ``ctx.workspace`` directly.
    """
    if ctx.workspace is None:
        raise _not_found()
    return ctx.workspace


# ---------------------------------------------------------------------------
# Self-review rule (target design §2.5)
# ---------------------------------------------------------------------------


async def self_review_blocked(
    db: AsyncSession, workspace_id: UUID | None, pr_author_login: str | None, user: User
) -> bool:
    """True when the actor may not act on their own PR.

    Active **only** in an ORG workspace with more than one member; disabled
    in PERSONAL workspaces and single-member ORG workspaces (§2.5).
    """
    if not workspace_id or not pr_author_login:
        return False

    workspace = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    if workspace is None or workspace.type != "ORG":
        return False

    # Union across BOTH membership tables — a member provisioned through an
    # invitation may exist in only one of them, and the rule is about real
    # people in the workspace.
    ws_ids: set[UUID] = set(
        (
            await db.execute(
                select(WorkspaceMember.user_id).where(
                    WorkspaceMember.workspace_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    org_ids: set[UUID] = set(
        (
            await db.execute(
                select(OrgMember.user_id)
                .join(Org, Org.id == OrgMember.org_id)
                .where(Org.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    member_count = len(ws_ids | org_ids)

    if member_count <= 1:
        return False

    if not user.login:
        return False
    return user.login.lower() == pr_author_login.lower()
