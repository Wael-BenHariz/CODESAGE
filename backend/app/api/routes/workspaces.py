"""Workspace endpoints for RBAC.

Authorization is delegated to ``app.security.workspace_access`` — this file
only holds business rules (name uniqueness, personal workspaces are not
deletable, no orphaning the last ORG_ADMIN). Guards:

* list/get      → membership in the workspace (``view``)
* settings      → ``repo_admin`` (ORG_ADMIN+, target design §2.3)
* member mgmt   → ``repo_admin`` (ORG_ADMIN+)
* create        → global ``ORG_ADMIN``/``PLATFORM_ADMIN`` (no workspace exists
                  yet, so the realm role is the only gate)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import (
    Org,
    OrgMember,
    Repository,
    User,
    Workspace,
    WorkspaceMember,
)
from app.security.dependencies import get_current_user
from app.security.roles import ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN, require_role
from app.security.workspace_access import (
    WorkspaceContext,
    capability_flags,
    check_permission_in_workspace,
    list_user_workspaces,
    membership_role,
    remove_membership,
    require_workspace,
    require_workspace_permission,
    sync_membership_role,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_MEMBER_ROLES = ("ORG_ADMIN", "REVIEWER", "DEVELOPER", "NONE")


def _workspace_payload(
    workspace: Workspace, role: str, owner_user_id: UUID | None = None
) -> dict:
    return {
        "id": str(workspace.id),
        "type": workspace.type,
        "name": workspace.name,
        "role": role,
        "is_personal": workspace.type == "PERSONAL",
        "github_account_login": workspace.github_account_login,
        "owner_user_id": (
            str(owner_user_id or workspace.owner_user_id)
            if (owner_user_id or workspace.owner_user_id)
            else None
        ),
        "capabilities": capability_flags(role),
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
    }


async def _count_org_admins(
    db: AsyncSession, workspace: Workspace, exclude_user_id: UUID | None = None
) -> int:
    """Distinct ORG_ADMINs of the workspace across BOTH membership tables.

    ``workspace_members`` may lag behind ``org_members`` (or vice versa) —
    counting the union is the only way the last-admin guard cannot be
    dodged by a row living in just one table.
    """
    admin_ids: set[UUID] = set()

    ws_query = select(WorkspaceMember.user_id).where(
        WorkspaceMember.workspace_id == workspace.id,
        WorkspaceMember.role == ROLE_ORG_ADMIN,
    )
    if exclude_user_id is not None:
        ws_query = ws_query.where(WorkspaceMember.user_id != exclude_user_id)
    admin_ids.update((await db.execute(ws_query)).scalars().all())

    if workspace.type == "ORG":
        org_query = (
            select(OrgMember.user_id)
            .join(Org, Org.id == OrgMember.org_id)
            .where(Org.workspace_id == workspace.id, OrgMember.role == ROLE_ORG_ADMIN)
        )
        if exclude_user_id is not None:
            org_query = org_query.where(OrgMember.user_id != exclude_user_id)
        admin_ids.update((await db.execute(org_query)).scalars().all())

    return len(admin_ids)


@router.get("", response_model=list[dict])
async def list_my_workspaces(
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """List all workspaces the user is a member of, with their effective role
    and capability flags (the frontend renders from those — §2.3)."""
    return [
        _workspace_payload(workspace, role)
        for workspace, role in await list_user_workspaces(db, current_user)
    ]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_org_workspace(
    name: str = Query(..., description="Name of the organization workspace"),
    github_account_login: str | None = Query(None, description="GitHub account login"),
    current_user: User = Depends(  # noqa: B008
        require_role(ROLE_PLATFORM_ADMIN, ROLE_ORG_ADMIN)  # noqa: B008
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Create a new organization workspace (global ORG_ADMIN/PLATFORM_ADMIN)."""
    result = await db.execute(
        select(Workspace).where(Workspace.type == "ORG", Workspace.name == name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workspace with name '{name}' already exists",
        )

    workspace = Workspace(
        type="ORG",
        name=name,
        github_account_login=github_account_login,
    )
    db.add(workspace)
    await db.flush()

    # Creator owns administration of the new workspace (§2.1/§2.3).
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id, user_id=current_user.id, role=ROLE_ORG_ADMIN
        )
    )
    await db.commit()
    await db.refresh(workspace)

    return _workspace_payload(workspace, ROLE_ORG_ADMIN)


@router.get("/{workspace_id}", response_model=dict)
async def get_workspace(
    ctx: WorkspaceContext = Depends(  # noqa: B008
        require_workspace_permission("view")  # noqa: B008
    ),
):
    """Get a workspace by ID (members only — non-members get a uniform 404)."""
    workspace = require_workspace(ctx)
    return _workspace_payload(workspace, ctx.effective_role, ctx.user.id)


@router.patch("/{workspace_id}", response_model=dict)
async def update_workspace(
    name: str | None = Query(None, description="New name for the workspace"),
    github_account_login: str | None = Query(
        None, description="New GitHub account login"
    ),
    ctx: WorkspaceContext = Depends(  # noqa: B008
        require_workspace_permission("repo_admin")  # noqa: B008
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Update a workspace — ORG_ADMIN+ in *this* workspace (§2.3 repo_admin)."""
    workspace = require_workspace(ctx)

    if name is not None and name != workspace.name:
        result = await db.execute(
            select(Workspace).where(
                Workspace.type == workspace.type,
                Workspace.name == name,
                Workspace.id != workspace.id,
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Another workspace with name '{name}' already exists",
            )
        workspace.name = name

    if github_account_login is not None:
        workspace.github_account_login = github_account_login

    await db.commit()
    await db.refresh(workspace)

    return _workspace_payload(workspace, ctx.effective_role, ctx.user.id)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    ctx: WorkspaceContext = Depends(  # noqa: B008
        require_workspace_permission("repo_admin")  # noqa: B008
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Delete a workspace — ORG_ADMIN+ in *this* workspace.

    Personal workspaces are permanent (§2.1: exactly one per user) and an
    ORG workspace may never lose its last ORG_ADMIN.
    """
    workspace = require_workspace(ctx)

    if workspace.type == "PERSONAL":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete personal workspace",
        )

    # repositories.workspace_id is ON DELETE CASCADE — deleting a workspace
    # that still holds repositories would silently wipe repos, PRs and
    # review history. Require an empty workspace instead (fail closed).
    repo_count = (
        await db.execute(
            select(Repository.id)
            .where(Repository.workspace_id == workspace.id)
            .limit(1)
        )
    ).first()
    if repo_count is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace still has repositories; disconnect them first",
        )

    # The actor is an admin (repo_admin passed) — the only blocker left is
    # adminship: deleting the sole admin orphans the workspace.
    remaining_admins = await _count_org_admins(
        db, workspace, exclude_user_id=ctx.user.id
    )
    if remaining_admins == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the last ORG_ADMIN in an organization workspace",
        )

    await db.delete(workspace)
    await db.commit()


@router.get("/{workspace_id}/members", response_model=list[dict])
async def list_workspace_members(
    ctx: WorkspaceContext = Depends(  # noqa: B008
        require_workspace_permission("view")  # noqa: B008
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """List all members of a workspace (members only).

    Reads both membership tables — a member provisioned through an
    org invitation (``org_members``) shows up even before a
    ``workspace_members`` row exists.
    """
    workspace = require_workspace(ctx)

    members: dict[UUID, dict] = {}

    rows = await db.execute(
        select(WorkspaceMember, User)
        .join(User, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace.id)
    )
    for membership, user in rows.all():
        members[user.id] = {
            "id": str(membership.id),
            "user_id": str(user.id),
            "username": user.login,
            "role": membership.role,
            "created_at": membership.created_at,
            "updated_at": membership.updated_at,
        }

    if workspace.type == "ORG":
        org_rows = await db.execute(
            select(OrgMember, User)
            .join(User, OrgMember.user_id == User.id)
            .join(Org, Org.id == OrgMember.org_id)
            .where(Org.workspace_id == workspace.id)
        )
        for org_member, user in org_rows.all():
            if user.id in members:
                continue  # workspace_members row already richer
            members[user.id] = {
                "id": None,
                "user_id": str(user.id),
                "username": user.login,
                "role": org_member.role,
                "created_at": getattr(org_member, "created_at", None),
                "updated_at": getattr(org_member, "updated_at", None),
            }

    return sorted(members.values(), key=lambda m: (m["username"] or "").lower())


@router.patch("/{workspace_id}/members/{user_id}", response_model=dict)
async def update_workspace_member_role(
    workspace_id: UUID = Path(...),  # noqa: B008
    user_id: UUID = Path(...),  # noqa: B008
    role: str = Query(
        ..., description="New role (ORG_ADMIN, REVIEWER, DEVELOPER, NONE)"
    ),
    ctx: WorkspaceContext = Depends(  # noqa: B008
        require_workspace_permission("repo_admin")  # noqa: B008
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Change a member's role — ORG_ADMIN+ in this workspace (§2.3).

    The role lands in **both** membership tables (authorization reads both
    and takes the ladder max, so a write to only one would be cancelled out
    by the stale row in the other).
    """
    if role not in _MEMBER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(_MEMBER_ROLES)}",
        )

    workspace = require_workspace(ctx)

    # Target must be a member of THIS workspace (either table) — uniform 404.
    target_role = await membership_role(db, user_id, workspace)
    if target_role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this workspace",
        )

    # Never orphan an ORG workspace: the last admin cannot be demoted.
    if (
        role != ROLE_ORG_ADMIN
        and workspace.type == "ORG"
        and target_role == ROLE_ORG_ADMIN
    ):
        remaining = await _count_org_admins(db, workspace, exclude_user_id=user_id)
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last ORG_ADMIN in an organization workspace",
            )

    await sync_membership_role(db, workspace, user_id, role)
    await db.commit()

    membership = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one()

    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "role": membership.role,
        "created_at": membership.created_at,
        "updated_at": membership.updated_at,
    }


@router.delete(
    "/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_workspace_member(
    workspace_id: UUID = Path(...),  # noqa: B008
    user_id: UUID = Path(...),  # noqa: B008
    ctx: WorkspaceContext = Depends(  # noqa: B008
        require_workspace_permission("repo_admin")  # noqa: B008
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Remove a member — ORG_ADMIN+ in this workspace (§2.3).

    You may not remove yourself (leave via your own action instead), and the
    last ORG_ADMIN of an ORG workspace may not be removed.
    """
    workspace = require_workspace(ctx)

    if user_id == ctx.user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself from a workspace",
        )

    target_role = await membership_role(db, user_id, workspace)
    if target_role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this workspace",
        )

    if target_role == ROLE_ORG_ADMIN and workspace.type == "ORG":
        remaining = await _count_org_admins(db, workspace, exclude_user_id=user_id)
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last ORG_ADMIN in an organization workspace",
            )

    await remove_membership(db, workspace, user_id)
    await db.commit()


# `check_permission_in_workspace` is re-exported for symmetry with the other
# RBAC route modules that guard resources they resolved themselves.
__all__ = ["check_permission_in_workspace", "router"]
