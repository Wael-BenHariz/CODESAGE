"""
API Routes Package
FastAPI routers for all API endpoints.
"""

from fastapi import APIRouter

from app.api.routes import auth, health, users, repositories, pull_requests, reviews, webhooks

# Main API router
api_router = APIRouter()

# Include all route modules
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(repositories.router, prefix="/repositories", tags=["Repositories"])
api_router.include_router(pull_requests.router, prefix="/pull-requests", tags=["Pull Requests"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["Reviews"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])

__all__ = ["api_router"]