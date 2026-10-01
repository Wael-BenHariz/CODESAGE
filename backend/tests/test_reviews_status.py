"""GET /reviews/{review_id}/status requires authentication.

Same contract as ``GET /reviews/{id}``: any authenticated user may read any
review (reviews are shared across users — no ownership filter), and nobody
may poll review status without a valid Keycloak access token.
"""

import uuid
from datetime import datetime, timezone

from conftest import make_keycloak_token

from app.config import settings
from app.db.models import GitHubInstallation, PullRequest, Repository, Review

API = settings.API_V1_PREFIX


async def test_status_without_token_401(client):
    """No Authorization header → 401 (generic body, no review lookup)."""
    resp = await client.get(f"{API}/reviews/{uuid.uuid4()}/status")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


async def test_status_with_token_200(client, db, user):
    """A valid token → 200 with the review's polling status."""
    # Minimal ownership chain: installation → repo → PR → review.
    installation = GitHubInstallation(
        app_id=1,
        installation_id=987654,
        account_id=1,
        account_login="test-owner",
        account_type="User",
    )
    db.add(installation)
    await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=111,
        name="demo",
        full_name="test-owner/demo",
    )
    db.add(repository)
    await db.flush()

    pull_request = PullRequest(
        repository_id=repository.id,
        github_pr_id=222,
        number=1,
        title="Add feature",
        author_login="test-owner",
        base_branch="main",
        head_branch="feature",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    db.add(pull_request)
    await db.flush()

    review = Review(
        pull_request_id=pull_request.id,
        user_id=user.id,
        status="processing",
        started_at=datetime.now(timezone.utc),
    )
    db.add(review)
    await db.commit()

    token = make_keycloak_token()  # DEVELOPER
    resp = await client.get(
        f"{API}/reviews/{review.id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_id"] == str(review.id)
    assert body["status"] == "processing"
    assert body["progress"] is None or 0 <= body["progress"] <= 100
