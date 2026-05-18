"""
Health Check Routes
System health and status endpoints.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, status

from app.db import engine

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Basic health check endpoint.
    Returns 200 OK if the service is running.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check():
    """
    Readiness check with database connectivity.
    Returns 200 OK if all dependencies are available.
    """
    checks = {
        "database": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Check database connectivity
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
            checks["database"] = True
    except Exception:
        checks["database"] = False
        return {
            "status": "not_ready",
            "checks": checks,
        }
    
    return {
        "status": "ready",
        "checks": checks,
    }


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check():
    """
    Kubernetes-style liveness probe.
    Returns 200 OK if the process is alive.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }