"""GET /pull-requests/repository/{id} must serialize ORM rows (UUID → str).

Regression for the 500 on ``?per_page=100``: ``PullRequestResponse`` declared
``id``/``repository_id`` as ``str`` but the ORM yields ``uuid.UUID``, which
Pydantic v2 refuses to coerce — ``model_validate(row)`` raised a ValidationError
and FastAPI turned it into a 500 for every repository holding at least one PR
(empty repositories still answered 200, which masked the bug).
"""

import uuid
from datetime import datetime, timezone

from conftest import make_keycloak_token

from app.config import settings
from app.db.models import (
    GitHubInstallation,
    PullRequest,
    Repository,
)
from app.schemas.pull_request import PullRequestResponse

API = settings.API_V1_PREFIX


def test_model_validate_accepts_uuid_fields():
    """A transient ORM row (UUID pks) validates without a ValidationError."""
    row = PullRequest(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        github_pr_id=4625484114,
        number=1,
        title="testing the reviewer",
        state="open",
        author_login="Wael-BenHariz",
        base_branch="master",
        head_branch="test",
        base_sha="a" * 40,
        head_sha="b" * 40,
        additions=310,
        deletions=0,
        changed_files=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    resp = PullRequestResponse.model_validate(row)

    assert isinstance(resp.id, str)
    assert resp.id == str(row.id)
    assert isinstance(resp.repository_id, str)
    assert resp.repository_id == str(row.repository_id)


async def test_list_with_pr_returns_200_not_500(client, db, user):
    """A repository holding a PR answers 200 with string ids."""
    installation = GitHubInstallation(
        app_id=1,
        installation_id=987656,
        account_id=1,
        account_login="test-owner",
        account_type="User",
    )
    db.add(installation)
    await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=333,
        name="demo",
        full_name="test-owner/demo",
    )
    db.add(repository)
    await db.flush()

    pull_request = PullRequest(
        repository_id=repository.id,
        github_pr_id=444,
        number=1,
        title="Add feature",
        author_login="test-owner",
        base_branch="main",
        head_branch="feature",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    db.add(pull_request)
    await db.commit()

    token = make_keycloak_token()
    resp = await client.get(
        f"{API}/pull-requests/repository/{repository.id}",
        params={"per_page": 100},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(pull_request.id)
    assert body["items"][0]["repository_id"] == str(repository.id)


async def test_list_unknown_repository_404(client, user):
    """An unknown repository id still 404s (never 500)."""
    token = make_keycloak_token()
    resp = await client.get(
        f"{API}/pull-requests/repository/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
