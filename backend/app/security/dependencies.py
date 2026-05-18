"""
Security Dependencies
FastAPI dependencies for authentication and authorization.
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import User
from app.security.jwt import token_manager

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user.
    
    Raises:
        HTTPException: If no valid token is provided
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"get_current_user - credentials: {credentials}")
    
    if not credentials:
        logger.error("No credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        logger.info(f"Verifying token type: {credentials.credentials[:20]}...")
        payload = token_manager.verify_token(credentials.credentials, token_type="access")
        logger.info(f"Token payload: {payload}")
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError as e:
        logger.error(f"JWTError: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Fetch user from database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Dependency to get the current user if authenticated, None otherwise.
    
    Useful for endpoints that have different behavior for authenticated vs anonymous users.
    """
    if not credentials:
        return None
    
    try:
        payload = token_manager.verify_token(credentials.credentials, token_type="access")
        user_id = payload.get("sub")
        
        if not user_id:
            return None
    except Exception:
        return None
    
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to require admin privileges.
    
    For now, checks if user has admin metadata. 
    Extend this for proper role-based access control.
    """
    # Placeholder for admin check - implement based on your requirements
    # For example, check if user has 'admin' role or specific permissions
    return current_user


async def require_repository_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to require access to a specific repository.
    
    Should be used with a path parameter for repository_id.
    """
    # This is a placeholder - implement repository-level access control
    return current_user