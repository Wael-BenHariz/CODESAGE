"""Notification endpoints for RBAC.

Notifications are strictly scoped to their recipient (``user_id``) — every
query filters on ``current_user.id``, so cross-user reads are structurally
impossible. The optional workspace filter reuses the central membership
check (both membership tables) rather than poking ``workspace_members``
directly.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import Notification, User
from app.security.dependencies import get_current_user
from app.security.workspace_access import check_permission_in_workspace

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _payload(notification: Notification) -> dict:
    return {
        "id": str(notification.id),
        "workspace_id": (
            str(notification.workspace_id) if notification.workspace_id else None
        ),
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "is_read": notification.is_read,
        "related_id": str(notification.related_id) if notification.related_id else None,
        "related_type": notification.related_type,
        "created_at": notification.created_at.isoformat(),
        "updated_at": notification.updated_at.isoformat(),
    }


@router.get("", response_model=list[dict])
async def list_notifications(
    workspace_id: UUID | None = Query(  # noqa: B008
        None, description="Filter by workspace ID"
    ),
    unread_only: bool = Query(False, description="Show only unread notifications"),
    limit: int = Query(
        50, ge=1, le=100, description="Maximum number of notifications to return"
    ),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """List the current user's notifications (own rows only)."""
    query = select(Notification).where(Notification.user_id == current_user.id)

    if workspace_id:
        # Membership required in the filtered workspace (uniform 404 if not).
        await check_permission_in_workspace(db, current_user, workspace_id, "view")
        query = query.where(Notification.workspace_id == workspace_id)

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    query = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    return [_payload(n) for n in result.scalars().all()]


@router.patch("/{notification_id}/read", response_model=dict)
async def mark_notification_as_read(
    notification_id: UUID = Path(...),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Mark one of your notifications as read (others' rows → 404)."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    notification.is_read = True
    await db.commit()
    await db.refresh(notification)

    return _payload(notification)


@router.patch("/read-all", response_model=dict)
async def mark_all_notifications_as_read(
    workspace_id: UUID | None = Query(  # noqa: B008
        None, description="Filter by workspace ID"
    ),
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Mark all of your notifications as read (optionally one workspace)."""
    stmt = update(Notification).where(Notification.user_id == current_user.id)

    if workspace_id:
        await check_permission_in_workspace(db, current_user, workspace_id, "view")
        stmt = stmt.where(Notification.workspace_id == workspace_id)

    result = await db.execute(stmt.values(is_read=True))
    await db.commit()

    return {"updated_count": result.rowcount}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID = Path(...),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Delete one of your notifications (others' rows → 404)."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    await db.delete(notification)
    await db.commit()
