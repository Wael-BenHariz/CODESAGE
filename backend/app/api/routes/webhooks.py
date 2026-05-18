"""
Webhook Routes
GitHub webhook handling endpoints.
"""

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.db.models import Repository, WebhookEvent, GitHubInstallation
from app.schemas.webhook import (
    WebhookProcessResult,
    PullRequestWebhookData,
)
from app.services.github import github_service

router = APIRouter()


@router.post("/github")
async def handle_github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle incoming GitHub webhook events.
    
    Supports:
    - pull_request: Trigger reviews and track PRs
    - installation: Handle app installation events
    - installation_repositories: Handle repository access changes
    """
    # Get raw body for signature verification
    body = await request.body()
    
    # Get signature and event type
    signature = request.headers.get("X-Hub-Signature-256", "")
    event_type = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    
    # Verify signature
    if not github_service.verify_webhook_signature(body, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )
    
    # Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )
    
    # Handle different event types
    if event_type == "pull_request":
        return await _handle_pull_request_event(request, payload, delivery_id, db)
    
    elif event_type == "installation":
        return await _handle_installation_event(payload, delivery_id, db)
    
    elif event_type == "installation_repositories":
        return await _handle_installation_repos_event(payload, delivery_id, db)
    
    else:
        # Acknowledge unknown events without processing
        return {
            "status": "acknowledged",
            "event_type": event_type,
            "message": "Event type not handled",
        }


async def _handle_pull_request_event(
    request: Request,
    payload: dict[str, Any],
    delivery_id: str,
    db: AsyncSession,
) -> WebhookProcessResult:
    """
    Handle pull_request webhook events.
    
    Creates/updates PR records and triggers reviews for opened/synchronize actions.
    """
    action = payload.get("action")
    pr_data = payload.get("pull_request", {})
    repo_data = payload.get("repository", {})
    installation = payload.get("installation", {})
    
    if not installation:
        return WebhookProcessResult(
            event_id="",
            processed=False,
            action_taken=None,
            error="No installation data in payload",
        )
    
    installation_id = installation.get("id")
    
    # Find or create repository record
    repo_result = await db.execute(
        select(Repository)
        .options(selectinload(Repository.installation))
        .where(Repository.github_repo_id == repo_data.get("id"))
    )
    repo = repo_result.scalar_one_or_none()
    
    if not repo:
        # Create new repository record
        repo = Repository(
            installation_id=installation_id,  # This needs to be a UUID, not int
            github_repo_id=repo_data.get("id"),
            name=repo_data.get("name", ""),
            full_name=repo_data.get("full_name", ""),
            private=repo_data.get("private", False),
            default_branch=repo_data.get("default_branch", "main"),
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
    
    # Create webhook event record
    webhook_event = WebhookEvent(
        repository_id=repo.id,
        event_type="pull_request",
        delivery_id=delivery_id,
        action=action,
        payload=payload,
        processed=False,
    )
    db.add(webhook_event)
    await db.commit()
    await db.refresh(webhook_event)
    
    # Process based on action
    if action in ["opened", "synchronize", "reopened"]:
        # Create or update PR record
        from app.db.models import PullRequest
        
        pr_result = await db.execute(
            select(PullRequest)
            .where(PullRequest.repository_id == repo.id)
            .where(PullRequest.github_pr_id == pr_data.get("id"))
        )
        existing_pr = pr_result.scalar_one_or_none()
        
        if existing_pr:
            # Update existing PR
            existing_pr.title = pr_data.get("title", "")
            existing_pr.body = pr_data.get("body")
            existing_pr.state = pr_data.get("state", "open")
            existing_pr.head_sha = pr_data.get("head", {}).get("sha", "")
            existing_pr.additions = pr_data.get("additions", 0)
            existing_pr.deletions = pr_data.get("deletions", 0)
            existing_pr.changed_files = pr_data.get("changed_files", 0)
        else:
            # Create new PR record
            base = pr_data.get("base", {})
            head = pr_data.get("head", {})
            user = pr_data.get("user", {})
            
            new_pr = PullRequest(
                repository_id=repo.id,
                github_pr_id=pr_data.get("id"),
                number=pr_data.get("number"),
                title=pr_data.get("title", ""),
                body=pr_data.get("body"),
                state=pr_data.get("state", "open"),
                author_login=user.get("login", ""),
                author_avatar_url=user.get("avatar_url"),
                base_branch=base.get("ref", ""),
                head_branch=head.get("ref", ""),
                base_sha=base.get("sha", ""),
                head_sha=head.get("sha", ""),
                additions=pr_data.get("additions", 0),
                deletions=pr_data.get("deletions", 0),
                changed_files=pr_data.get("changed_files", 0),
            )
            db.add(new_pr)
        
        await db.commit()
        
        # Trigger review if repository is enabled
        if repo.enabled:
            from app.db.models import Review
            from app.workers.review_queue import queue_review
            
            # Check for pending reviews
            pending = await db.execute(
                select(Review)
                .where(Review.pull_request_id == repo.id)
                .where(Review.status.in_(["pending", "processing"]))
            )
            
            if not pending.scalar_one_or_none():
                # Create new review
                review = Review(
                    pull_request_id=repo.id,
                    status="pending",
                    started_at=datetime.now(timezone.utc),
                )
                db.add(review)
                await db.commit()
                await db.refresh(review)
                
                # Queue review job
                await queue_review(str(review.id))
                
                # Mark event as processed
                webhook_event.processed = True
                await db.commit()
                
                return WebhookProcessResult(
                    event_id=str(webhook_event.id),
                    processed=True,
                    action_taken="created_review",
                    review_id=str(review.id),
                )
        
        # Mark event as processed
        webhook_event.processed = True
        await db.commit()
        
        return WebhookProcessResult(
            event_id=str(webhook_event.id),
            processed=True,
            action_taken=f"processed_{action}",
        )
    
    elif action == "closed":
        # Update PR state
        from app.db.models import PullRequest
        
        pr_result = await db.execute(
            select(PullRequest)
            .where(PullRequest.repository_id == repo.id)
            .where(PullRequest.github_pr_id == pr_data.get("id"))
        )
        pr = pr_result.scalar_one_or_none()
        
        if pr:
            merged = pr_data.get("merged", False)
            pr.state = "merged" if merged else "closed"
            await db.commit()
        
        webhook_event.processed = True
        await db.commit()
        
        return WebhookProcessResult(
            event_id=str(webhook_event.id),
            processed=True,
            action_taken="closed_pr",
        )
    
    else:
        # Acknowledge other actions
        webhook_event.processed = True
        await db.commit()
        
        return WebhookProcessResult(
            event_id=str(webhook_event.id),
            processed=True,
            action_taken=f"acknowledged_{action}",
        )


async def _handle_installation_event(
    payload: dict[str, Any],
    delivery_id: str,
    db: AsyncSession,
) -> dict:
    """
    Handle installation webhook events.
    
    Creates/updates/deletes GitHub App installation records.
    """
    action = payload.get("action")
    installation = payload.get("installation", {})
    
    installation_id = installation.get("id")
    account = installation.get("account", {})
    
    if action == "created" or action == "suspended":
        # Create or update installation record
        from app.db.models import GitHubInstallation
        
        result = await db.execute(
            select(GitHubInstallation)
            .where(GitHubInstallation.installation_id == installation_id)
        )
        record = result.scalar_one_or_none()
        
        if record:
            # Update existing
            record.account_login = account.get("login", "")
            record.account_type = account.get("type", "User")
            record.permissions = installation.get("permissions", {})
        else:
            # Create new
            record = GitHubInstallation(
                app_id=installation.get("app_id", 0),
                installation_id=installation_id,
                account_id=account.get("id", 0),
                account_login=account.get("login", ""),
                account_type=account.get("type", "User"),
                permissions=installation.get("permissions", {}),
            )
            db.add(record)
        
        await db.commit()
        
        return {
            "status": "success",
            "action": action,
            "installation_id": installation_id,
        }
    
    elif action == "deleted" or action == "unsuspended":
        # Delete installation and cascade to repositories
        from app.db.models import GitHubInstallation
        
        result = await db.execute(
            select(GitHubInstallation)
            .where(GitHubInstallation.installation_id == installation_id)
        )
        record = result.scalar_one_or_none()
        
        if record:
            await db.delete(record)
            await db.commit()
        
        return {
            "status": "success",
            "action": action,
            "installation_id": installation_id,
        }
    
    return {
        "status": "acknowledged",
        "action": action,
    }


async def _handle_installation_repos_event(
    payload: dict[str, Any],
    delivery_id: str,
    db: AsyncSession,
) -> dict:
    """
    Handle installation_repositories webhook events.
    
    Updates repository access for an installation.
    """
    action = payload.get("action")  # added, removed
    installation = payload.get("installation", {})
    repos_added = payload.get("repositories_added", [])
    repos_removed = payload.get("repositories_removed", [])
    
    installation_id = installation.get("id")
    
    # Find installation record
    from app.db.models import GitHubInstallation
    
    result = await db.execute(
        select(GitHubInstallation)
        .where(GitHubInstallation.installation_id == installation_id)
    )
    install_record = result.scalar_one_or_none()
    
    if not install_record:
        return {
            "status": "error",
            "message": "Installation not found",
        }
    
    # Add new repositories
    for repo in repos_added:
        from app.db.models import Repository
        
        existing = await db.execute(
            select(Repository)
            .where(Repository.github_repo_id == repo.get("id"))
        )
        if not existing.scalar_one_or_none():
            new_repo = Repository(
                installation_id=install_record.id,
                github_repo_id=repo.get("id"),
                name=repo.get("name", ""),
                full_name=repo.get("full_name", ""),
                private=repo.get("private", False),
                default_branch=repo.get("default_branch", "main"),
            )
            db.add(new_repo)
    
    # Remove repositories
    for repo in repos_removed:
        from app.db.models import Repository
        
        result = await db.execute(
            select(Repository)
            .where(Repository.github_repo_id == repo.get("id"))
        )
        record = result.scalar_one_or_none()
        if record:
            await db.delete(record)
    
    await db.commit()
    
    return {
        "status": "success",
        "repos_added": len(repos_added),
        "repos_removed": len(repos_removed),
    }