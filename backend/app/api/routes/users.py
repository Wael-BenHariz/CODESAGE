"""
User Routes
User management and profile endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import User, OAuthToken
from app.schemas.user import (
    UserResponse,
    UserUpdate,
    UserListResponse,
    CurrentUser,
)
from app.security.dependencies import get_current_user

router = APIRouter()


@router.get("/me", response_model=CurrentUser)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Get current user's profile.
    """
    return CurrentUser(
        id=str(current_user.id),
        github_id=current_user.github_id,
        login=current_user.login,
        email=current_user.email,
        name=current_user.name,
        avatar_url=current_user.avatar_url,
        is_active=current_user.is_active,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get user by ID.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return UserResponse.model_validate(user)


@router.get("", response_model=UserListResponse)
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by login or email"),
):
    """
    List all users (admin only).
    """
    # Build query
    query = select(User)
    count_query = select(func.count(User.id))
    
    # Apply search filter
    if search:
        search_filter = User.login.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Get paginated results
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page).order_by(User.created_at.desc())
    
    result = await db.execute(query)
    users = result.scalars().all()
    
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update current user's profile.
    """
    # Update allowed fields
    if update_data.email is not None:
        current_user.email = update_data.email
    if update_data.name is not None:
        current_user.name = update_data.name
    if update_data.avatar_url is not None:
        current_user.avatar_url = update_data.avatar_url
    
    await db.commit()
    await db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete current user's account and all associated data.
    This action is irreversible.
    """
    # Delete all tokens first
    await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == current_user.id)
    )
    
    # Delete user (cascades to related records)
    await db.delete(current_user)
    await db.commit()