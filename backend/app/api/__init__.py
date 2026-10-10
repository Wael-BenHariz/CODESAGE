"""
API Routes Package
FastAPI routers for all API endpoints.
"""

from fastapi import APIRouter

from app.api.routes import (
    auth,
    github_repos,
    health,
    invitations,
    orgs,
    platform,
    pull_requests,
    repositories,
    reviews,
    settings,
    users,
    webhooks,
)

# Main API router
api_router = APIRouter()

# Include all route modules
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(
    repositories.router, prefix="/repositories", tags=["Repositories"]
)
api_router.include_router(github_repos.router, prefix="/github", tags=["GitHub App"])
api_router.include_router(
    pull_requests.router, prefix="/pull-requests", tags=["Pull Requests"]
)
api_router.include_router(reviews.router, prefix="/reviews", tags=["Reviews"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
api_router.include_router(settings.router, prefix="/settings", tags=["LLM Settings"])
api_router.include_router(orgs.router, prefix="/orgs", tags=["Organizations"])
# Invitations: the org-nested half rides the /orgs prefix; the token-keyed
# half (public preview + authenticated accept) mounts at /invitations.
api_router.include_router(invitations.org_router, prefix="/orgs", tags=["Invitations"])
api_router.include_router(
    invitations.router, prefix="/invitations", tags=["Invitations"]
)
api_router.include_router(
    platform.router, prefix="/platform", tags=["Platform Settings"]
)

__all__ = ["api_router"]
