"""Webhook duplicate-guard vs org ``posting_mode`` (regression).

The duplicate guard blocks a second queueing for the same
``(action, pull_request id, head sha)`` when a review already exists for the
PR — but it must not swallow a reopen that happens *after* the org changed
its ``posting_mode``. Live incident 2026-10-08: org switched
``auto → staged``, the PR was reopened without new commits, and the webhook
answered ``Skipping duplicate review for …@6953901 (action=reopened)`` —
no staged review was ever produced (the guard compared events, not settings).

Contract under test (``app/api/routes/webhooks.py``):

* prior ``reopened`` event + existing ``auto`` review + org now ``staged``
  → ``queued`` (a new review row is created, so the staged workflow runs)
* settings unchanged (effective posting_mode equals the existing review's)
  → still ``skipped`` — the guard's idempotency stays intact
* an error while resolving settings must never 500 the webhook; it falls
  back to the original skip behavior
"""

import json

from sqlalchemy import select

from app.config import settings
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgSetting,
    PullRequest,
    Repository,
    Review,
    User,
    WatchedRepo,
    WebhookEvent,
)
from app.services.github import github_service

API = settings.API_V1_PREFIX

INSTALLATION_ID = 42424242
GH_REPO_ID = 777000777
PR_GH_ID = 888000888
HEAD_SHA = "6953901888661422d1954a1199a5a239052ffa47"
OLD_DELIVERY = "11111111-2222-3333-4444-555555555555"
NEW_DELIVERY = "99999999-8888-7777-6666-555555555555"


async def _seed(db, *, existing_posting_mode: str, org_posting_mode: str | None):
    """Installation + watched repo + org + PR with one finished review and a
    prior processed ``reopened`` delivery at ``HEAD_SHA`` (the guard's first
    half). ``org_posting_mode=None`` seeds no ``org_settings`` row at all."""
    install = GitHubInstallation(
        app_id=12345,
        installation_id=INSTALLATION_ID,
        account_id=1,
        account_login="wael-test",
        account_type="user",
    )
    db.add(install)
    await db.flush()

    owner = User(
        github_id=111222333,
        login="wael-test",
        keycloak_id="kc-sub-webhook-owner",
        role="DEVELOPER",
        github_installation_id=INSTALLATION_ID,
    )
    db.add(owner)
    await db.flush()

    repo = Repository(
        installation_id=install.id,
        github_repo_id=GH_REPO_ID,
        name="First_Project",
        full_name="wael-test/First_Project",
        private=False,
        default_branch="main",
    )
    db.add(repo)
    await db.flush()

    db.add(
        WatchedRepo(
            user_id=owner.id,
            repo_id=GH_REPO_ID,
            repo_name="wael-test/First_Project",
            enabled=True,
        )
    )

    org = Org(name="wael-test", account_type="user", installation_id=INSTALLATION_ID)
    db.add(org)
    await db.flush()

    if org_posting_mode is not None:
        db.add(OrgSetting(org_id=org.id, posting_mode=org_posting_mode))

    pr = PullRequest(
        repository_id=repo.id,
        github_pr_id=PR_GH_ID,
        number=1,
        title="Add feature",
        body="",
        state="open",
        author_login="wael-test",
        base_branch="main",
        head_branch="feature",
        base_sha="a" * 40,
        head_sha=HEAD_SHA,
    )
    db.add(pr)
    await db.flush()

    db.add(
        Review(
            pull_request_id=pr.id,
            status="completed",
            posting_mode=existing_posting_mode,
        )
    )
    db.add(
        WebhookEvent(
            repository_id=repo.id,
            event_type="pull_request",
            delivery_id=OLD_DELIVERY,
            action="reopened",
            payload={"pull_request": {"id": PR_GH_ID, "head": {"sha": HEAD_SHA}}},
            processed=True,
        )
    )
    await db.commit()


def _reopen_body() -> bytes:
    return json.dumps(
        {
            "action": "reopened",
            "installation": {"id": INSTALLATION_ID},
            "repository": {
                "id": GH_REPO_ID,
                "name": "First_Project",
                "full_name": "wael-test/First_Project",
                "private": False,
                "default_branch": "main",
            },
            "pull_request": {
                "id": PR_GH_ID,
                "number": 1,
                "title": "Add feature",
                "body": "",
                "state": "open",
                "head": {"sha": HEAD_SHA, "ref": "feature"},
                "base": {"sha": "a" * 40, "ref": "main"},
                "user": {"login": "wael-test"},
                "additions": 10,
                "deletions": 2,
                "changed_files": 1,
            },
        }
    ).encode()


async def _post_reopened(client, delivery_id: str = NEW_DELIVERY):
    body = _reopen_body()
    return await client.post(
        f"{API}/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": github_service.generate_webhook_signature(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
        },
    )


async def _reviews(db) -> list[Review]:
    return list((await db.execute(select(Review))).scalars().all())


async def test_reopen_after_staged_switch_queues_new_review(client, db):
    """auto → staged since the last review: the guard must let the reopen
    through at an unchanged head sha so the staged workflow can run."""
    await _seed(db, existing_posting_mode="auto", org_posting_mode="staged")

    resp = await _post_reopened(client)

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    reviews = await _reviews(db)
    assert len(reviews) == 2
    fresh = [r for r in reviews if r.status == "pending"]
    assert len(fresh) == 1


async def test_reopen_with_unchanged_settings_is_still_skipped(client, db):
    """Guard intact: no org override (effective auto) vs an auto review →
    the duplicate skip still applies and no second review is created."""
    await _seed(db, existing_posting_mode="auto", org_posting_mode=None)

    resp = await _post_reopened(client)

    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"
    assert len(await _reviews(db)) == 1


async def test_reopen_after_staged_review_at_staged_is_skipped(client, db):
    """Idempotency: a staged review already exists and the org still runs
    staged → the reopen must not queue a third run."""
    await _seed(db, existing_posting_mode="staged", org_posting_mode="staged")

    resp = await _post_reopened(client)

    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"
    assert len(await _reviews(db)) == 1
