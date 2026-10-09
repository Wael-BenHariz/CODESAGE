"""Install request endpoints for RBAC."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import InstallRequest, Notification, User, WorkspaceMember
from app.security.dependencies import get_current_user
from app.security.workspace_access import (
    check_permission_in_workspace,
    list_user_workspaces,
)

router = APIRouter(prefix="/install-requests", tags=["install-requests"])


async def _notify_workspace_admins(
    db: AsyncSession,
    workspace_id: UUID,
    current_user: User,
    install_request: InstallRequest,
) -> None:
    """In-app notification to every ORG_ADMIN of the workspace (§2.5).

    Reads both membership tables (drift-proof) and skips the requester —
    an admin requesting their own install needs no ping.
    """
    from app.db.models import Org, OrgMember

    admin_ids: set[UUID] = set()

    ws_admins = await db.execute(
        select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "ORG_ADMIN",
        )
    )
    admin_ids.update(ws_admins.scalars().all())

    org_admins = await db.execute(
        select(OrgMember.user_id)
        .join(Org, Org.id == OrgMember.org_id)
        .where(Org.workspace_id == workspace_id, OrgMember.role == "ORG_ADMIN")
    )
    admin_ids.update(org_admins.scalars().all())

    requester = current_user.id
    for admin_id in admin_ids:
        if admin_id == requester:
            continue
        db.add(
            Notification(
                user_id=admin_id,
                workspace_id=workspace_id,
                type="install_request",
                title="GitHub App install requested",
                message=(
                    f"{current_user.login} requested the GitHub App install "
                    "for this workspace"
                ),
                related_id=install_request.id,
                related_type="install_request",
            )
        )


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_install_request(
    workspace_id: UUID = Query(  # noqa: B008
        ..., description="Workspace to request the GitHub App install for"
    ),
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Create an install request for the GitHub App in a workspace (§2.5).

    The caller must be a member with at least DEVELOPER (REQUEST/TRIGGER
    role) in that workspace — this is the flow a non-admin member of an ORG
    workspace uses to ask an ORG_ADMIN to install the App. ORG_ADMINs are
    notified in-app.
    """
    # Unknown workspace / non-member → 404, under-role → 403.
    await check_permission_in_workspace(db, current_user, workspace_id, "trigger")

    # Check if there's already a pending install request for this workspace by this user
    existing_result = await db.execute(
        select(InstallRequest).where(
            InstallRequest.workspace_id == workspace_id,
            InstallRequest.requested_by == current_user.id,
            InstallRequest.status == "PENDING",
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending install request for this workspace",
        )

    # Create the install request
    install_request = InstallRequest(
        workspace_id=workspace_id,
        requested_by=current_user.id,
        status="PENDING",
    )
    db.add(install_request)
    await db.flush()
    await _notify_workspace_admins(db, workspace_id, current_user, install_request)
    await db.commit()
    await db.refresh(install_request)

    return {
        "id": str(install_request.id),
        "workspace_id": str(install_request.workspace_id),
        "requested_by": str(install_request.requested_by),
        "status": install_request.status,
        "created_at": install_request.created_at.isoformat(),
        "updated_at": install_request.updated_at.isoformat(),
    }


@router.get("", response_model=list[dict])
async def list_install_requests(
    workspace_id: UUID | None = Query(  # noqa: B008
        None, description="Filter by workspace ID"
    ),
    status_filter: str | None = Query(
        None, description="Filter by status (PENDING, APPROVED, REJECTED)"
    ),
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """List install requests.

    Users can see install requests for workspaces they are members of.
    """
    # Accessible workspaces = personal + every membership, merged from both
    # membership tables (see workspace_access.list_user_workspaces).
    accessible_workspace_ids = [
        workspace.id
        for workspace, _role in await list_user_workspaces(db, current_user)
    ]

    if not accessible_workspace_ids:
        return []  # User is not a member of any workspace

    # Build query for install requests
    query = select(InstallRequest).where(
        InstallRequest.workspace_id.in_(accessible_workspace_ids)
    )

    # Apply workspace filter if specified
    if workspace_id:
        if workspace_id not in accessible_workspace_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to specified workspace",
            )
        query = query.where(InstallRequest.workspace_id == workspace_id)

    # Apply status filter if specified
    if status_filter:
        if status_filter not in ["PENDING", "APPROVED", "REJECTED"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid status filter. Must be PENDING, APPROVED, or REJECTED",
            )
        query = query.where(InstallRequest.status == status_filter)

    # Order by creation date (newest first)
    query = query.order_by(InstallRequest.created_at.desc())

    # Execute query
    result = await db.execute(query)
    install_requests = result.scalars().all()

    # Build response
    requests = []
    for request in install_requests:
        requests.append(
            {
                "id": str(request.id),
                "workspace_id": str(request.workspace_id),
                "requested_by": str(request.requested_by),
                "status": request.status,
                "created_at": request.created_at.isoformat(),
                "updated_at": request.updated_at.isoformat(),
            }
        )

    return requests


@router.patch("/{request_id}/approve", response_model=dict)
async def approve_install_request(
    request_id: UUID = Path(...),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Approve an install request.

    Only users in the REPO_ADMIN_ROLES (ORG_ADMIN, PLATFORM_ADMIN) can approve install requests.
    """
    # Get the install request
    result = await db.execute(
        select(InstallRequest).where(InstallRequest.id == request_id)
    )
    install_request = result.scalar_one_or_none()

    if not install_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Install request not found"
        )

    # Check if request is already resolved
    if install_request.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Install request is already {install_request.status.lower()}",
        )

    # Approving = ORG_ADMIN+ (REPO_ADMIN_ROLES, §2.3) in the request's
    # workspace — unknown workspace / non-member → 404, under-role → 403.
    await check_permission_in_workspace(
        db, current_user, install_request.workspace_id, "repo_admin"
    )

    # Approve the request
    install_request.status = "APPROVED"
    install_request.resolved_by = current_user.id
    from datetime import datetime, timezone

    install_request.resolved_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(install_request)

    return {
        "id": str(install_request.id),
        "workspace_id": str(install_request.workspace_id),
        "requested_by": str(install_request.requested_by),
        "status": install_request.status,
        "resolved_by": str(install_request.resolved_by),
        "resolved_at": (
            install_request.resolved_at.isoformat()
            if install_request.resolved_at
            else None
        ),
        "created_at": install_request.created_at.isoformat(),
        "updated_at": install_request.updated_at.isoformat(),
    }


@router.patch("/{request_id}/reject", response_model=dict)
async def reject_install_request(
    request_id: UUID = Path(...),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Reject an install request.

    Only users in the REPO_ADMIN_ROLES (ORG_ADMIN, PLATFORM_ADMIN) can reject install requests.
    """
    # Get the install request
    result = await db.execute(
        select(InstallRequest).where(InstallRequest.id == request_id)
    )
    install_request = result.scalar_one_or_none()

    if not install_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Install request not found"
        )

    # Check if request is already resolved
    if install_request.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Install request is already {install_request.status.lower()}",
        )

    # Rejecting = ORG_ADMIN+ (REPO_ADMIN_ROLES, §2.3) in the request's
    # workspace — unknown workspace / non-member → 404, under-role → 403.
    await check_permission_in_workspace(
        db, current_user, install_request.workspace_id, "repo_admin"
    )

    # Reject the request
    install_request.status = "REJECTED"
    install_request.resolved_by = current_user.id
    from datetime import datetime, timezone

    install_request.resolved_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(install_request)

    return {
        "id": str(install_request.id),
        "workspace_id": str(install_request.workspace_id),
        "requested_by": str(install_request.requested_by),
        "status": install_request.status,
        "resolved_by": str(install_request.resolved_by),
        "resolved_at": (
            install_request.resolved_at.isoformat()
            if install_request.resolved_at
            else None
        ),
        "created_at": install_request.created_at.isoformat(),
        "updated_at": install_request.updated_at.isoformat(),
    }
