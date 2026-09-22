"""
Webhook Routes
GitHub webhook handling endpoints.
"""

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.db.models import GitHubInstallation, PullRequest, Repository, Review, User, WatchedRepo, WebhookEvent
from app.schemas.webhook import WebhookProcessResult
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
        return await _handle_pull_request_event(payload, delivery_id, db)
    
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
    install_record = await _get_installation_record(db, installation_id)
    if not install_record:
        installation_data = await github_service.get_app_installation(installation_id)
        install_record = await _upsert_installation_record(db, installation_data)
        await db.commit()
    
    # Find or create repository record for the real GitHub App installation.
    repo_result = await db.execute(
        select(Repository)
        .options(selectinload(Repository.installation))
        .where(Repository.github_repo_id == repo_data.get("id"))
    )
    repo = repo_result.scalar_one_or_none()
    
    if not repo:
        # Create new repository record
        repo = Repository(
            installation_id=install_record.id,
            github_repo_id=repo_data.get("id"),
            name=repo_data.get("name", ""),
            full_name=repo_data.get("full_name", ""),
            private=repo_data.get("private", False),
            default_branch=repo_data.get("default_branch", "main"),
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
    else:
        repo.installation_id = install_record.id
        repo.name = repo_data.get("name", repo.name)
        repo.full_name = repo_data.get("full_name", repo.full_name)
        repo.private = repo_data.get("private", repo.private)
        repo.default_branch = repo_data.get("default_branch", repo.default_branch)
        await db.commit()
    
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
            pr_record = existing_pr
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
            pr_record = new_pr
        
        await db.commit()
        await db.refresh(pr_record)

        # Resolve installation owner(s): users whose column matches this
        # installation; the first one watching the repo (enabled) wins.
        owners = (
            await db.execute(
                select(User)
                .where(User.github_installation_id == installation_id)
                .order_by(User.created_at.asc())
            )
        ).scalars().all()
        watched_repo = None
        for owner in owners:
            watched_repo = await db.scalar(
                select(WatchedRepo).where(
                    WatchedRepo.repo_id == repo_data.get("id"),
                    WatchedRepo.user_id == owner.id,
                    WatchedRepo.enabled.is_(True),
                )
            )
            if watched_repo:
                break

        if not watched_repo:
            webhook_event.processed = True
            await db.commit()
            if not owners:
                reason = "no user linked to this installation"
            else:
                reason = "repository not selected by installation owner"
            return {
                "status": "ignored",
                "reason": reason,
            }
        
        # Trigger review -- watched_repos.enabled is the single review switch
        # (legacy repositories.enabled is display-only and no longer gates).
        from app.workers.review_queue import queue_review
            
        # Check for pending reviews
        pending = await db.execute(
            select(Review)
            .where(Review.pull_request_id == pr_record.id)
            .where(Review.status.in_(["pending", "processing"]))
        )
            
        if not pending.scalar_one_or_none():
            # Create new review
            review = Review(
                pull_request_id=pr_record.id,
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
    
    if action in ["created", "suspended", "unsuspended"]:
        # Create or update installation record
        record = await _upsert_installation_record(db, installation)

        for repo_data in payload.get("repositories", []):
            await _upsert_repository_record(db, record, repo_data)

        await db.commit()
        
        return {
            "status": "success",
            "action": action,
            "installation_id": installation_id,
        }
    
    elif action == "deleted":
        # Delete installation and cascade to repositories; unlink users so
        # /github/status flips back to "not installed".
        await db.execute(
            update(User)
            .where(User.github_installation_id == installation_id)
            .values(github_installation_id=None)
        )
        await db.commit()
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
    
    install_record = await _get_installation_record(db, installation_id)
    
    if not install_record:
        return {
            "status": "error",
            "message": "Installation not found",
        }
    
    # Add new repositories
    for repo in repos_added:
        await _upsert_repository_record(db, install_record, repo)
    
    # Remove repositories (and turn off the review switch for them)
    removed_ids = [repo.get("id") for repo in repos_removed if repo.get("id")]
    for repo in repos_removed:
        await _delete_repository_record(db, repo.get("id"))
    if removed_ids:
        await db.execute(
            update(WatchedRepo)
            .where(WatchedRepo.repo_id.in_(removed_ids))
            .values(enabled=False)
        )
    
    await db.commit()
    
    return {
        "status": "success",
        "repos_added": len(repos_added),
        "repos_removed": len(repos_removed),
    }


async def _get_installation_record(
    db: AsyncSession,
    installation_id: int,
) -> GitHubInstallation | None:
    result = await db.execute(
        select(GitHubInstallation).where(GitHubInstallation.installation_id == installation_id)
    )
    return result.scalar_one_or_none()


async def _upsert_installation_record(
    db: AsyncSession,
    installation_data: dict[str, Any],
) -> GitHubInstallation:
    installation_id = installation_data.get("id")
    account = installation_data.get("account", {})
    record = await _get_installation_record(db, installation_id)

    if record:
        record.app_id = installation_data.get("app_id", record.app_id)
        record.account_id = account.get("id", record.account_id)
        record.account_login = account.get("login", record.account_login)
        record.account_type = account.get("type", record.account_type)
        record.permissions = installation_data.get("permissions", record.permissions)
        return record

    record = GitHubInstallation(
        app_id=installation_data.get("app_id", 0),
        installation_id=installation_id,
        account_id=account.get("id", 0),
        account_login=account.get("login", ""),
        account_type=account.get("type", "User"),
        permissions=installation_data.get("permissions", {}),
    )
    db.add(record)
    await db.flush()
    return record


async def _upsert_repository_record(
    db: AsyncSession,
    installation: GitHubInstallation,
    repo_data: dict[str, Any],
) -> Repository:
    result = await db.execute(
        select(Repository).where(Repository.github_repo_id == repo_data.get("id"))
    )
    record = result.scalar_one_or_none()
    if record:
        record.installation_id = installation.id
        record.name = repo_data.get("name", record.name)
        record.full_name = repo_data.get("full_name", record.full_name)
        record.private = repo_data.get("private", record.private)
        record.default_branch = repo_data.get("default_branch", record.default_branch)
        return record

    record = Repository(
        installation_id=installation.id,
        github_repo_id=repo_data.get("id"),
        name=repo_data.get("name", ""),
        full_name=repo_data.get("full_name", ""),
        private=repo_data.get("private", False),
        default_branch=repo_data.get("default_branch", "main"),
        enabled=True,
    )
    db.add(record)
    await db.flush()
    return record


async def _delete_repository_record(db: AsyncSession, github_repo_id: int) -> None:
    result = await db.execute(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    )
    record = result.scalar_one_or_none()
    if record:
        await db.delete(record)
