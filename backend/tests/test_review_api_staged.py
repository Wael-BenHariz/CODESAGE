"""Step 7 — staged posting API + the F3 org retrofit (plan §3, flags F2/F3).

Contracts covered here:

- **F3 retrofit**: every pre-existing review/pull-request route now
  resolves ``review/PR -> repo -> installation -> org`` — unknown id and
  cross-org return the *same* 404 detail, one cross-org test per
  endpoint; ``GET /reviews`` filters to the caller's orgs (PLATFORM_ADMIN
  sees everything).
- **Guards**: NONE is rejected 403 on writes *before* any lookup; a
  PLATFORM_ADMIN without a membership row reads (F2 bypass) but gets 404
  on the staged mutations (F2 carve-out: summary/dismiss/restore/post);
  the legacy mutations keep the read-style bypass.
- **Summary**: editable only while ``posted_at IS NULL`` (409 after a
  post), >60 000 chars → 422 (schema cap = ``EDITED_SUMMARY_MAX_CHARS``).
- **Dismiss/restore**: comment outside the review → 404; the flags
  round-trip through ``GET /reviews/{id}``.
- **Post**: preconditions checked inside a ``FOR UPDATE`` row lock —
  auto mode / not ready / already posted → 409, concurrent posts have
  exactly one winner, GitHub failure → retryable 502 with ``posted_at``
  kept NULL and ``error_message`` stored.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from importlib import import_module
from types import SimpleNamespace

import pytest_asyncio
from conftest import make_keycloak_token

from app.config import settings
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    PullRequest,
    Repository,
    Review,
    ReviewComment,
    User,
)
from app.services.review_posting import EDITED_SUMMARY_MAX_CHARS, ReviewPostError

API = settings.API_V1_PREFIX
_REVIEWS = f"{API}/reviews"
_PRS = f"{API}/pull-requests"

_INSTALLATION_A = 777001
_INSTALLATION_B = 777002

# Two findings per review: an error (kept) and an info (dismissed in the
# posting tests so the body assertions can prove exclusion).
_ERROR_MSG = "Dangerous call: fix @alice before merge"
_INFO_MSG = "Minor nit about naming"


def _auth(keycloak_id: str, roles: tuple[str, ...] = ("DEVELOPER",)) -> dict:
    return {
        "Authorization": f"Bearer {make_keycloak_token(sub=keycloak_id, roles=roles)}"
    }


async def _make_user(db, keycloak_id: str, *, role: str = "DEVELOPER") -> User:
    row = User(keycloak_id=keycloak_id, login=keycloak_id, role=role)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _make_chain(
    db,
    *,
    installation_id: int,
    owner: str,
    org_name: str,
    number: int,
    status: str = "ready_to_post",
    posting_mode: str = "staged",
    summary: str = "Looks good overall.",
) -> SimpleNamespace:
    """installation + org + repo + PR + review + 2 comments (committed)."""
    installation = GitHubInstallation(
        app_id=1,
        installation_id=installation_id,
        account_id=installation_id,
        account_login=owner,
        account_type="User",
    )
    db.add(installation)
    await db.flush()

    org = Org(name=org_name, account_type="User", installation_id=installation_id)
    db.add(org)
    await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=installation_id,
        name="demo",
        full_name=f"{owner}/demo",
    )
    db.add(repository)
    await db.flush()

    pr = PullRequest(
        repository_id=repository.id,
        github_pr_id=number,
        number=number,
        title="Change",
        author_login=owner,
        base_branch="main",
        head_branch="feature",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    db.add(pr)
    await db.flush()

    now = datetime.now(timezone.utc)
    review = Review(
        pull_request_id=pr.id,
        status=status,
        posting_mode=posting_mode,
        summary=summary,
        started_at=now,
        completed_at=now,
    )
    db.add(review)
    await db.flush()

    db.add_all(
        [
            ReviewComment(
                review_id=review.id,
                pull_request_id=pr.id,
                file_path="src/a.py",
                line_number=10,
                body=_ERROR_MSG,
                severity="error",
                category="bug",
            ),
            ReviewComment(
                review_id=review.id,
                pull_request_id=pr.id,
                file_path="src/b.py",
                body=_INFO_MSG,
                severity="info",
                category="style",
            ),
        ]
    )
    await db.commit()
    await db.refresh(review, ["comments"])
    return SimpleNamespace(org=org, repo=repository, pr=pr, review=review)


@pytest_asyncio.fixture
async def stage(db):
    """Org A's review (member: dev_a) and org B's review (member: dev_b).

    Plus: a global PLATFORM_ADMIN with *no* membership row, and a
    membership-carrying user whose JWT role is NONE (to prove NONE-first).
    """
    a = await _make_chain(
        db, installation_id=_INSTALLATION_A, owner="owner-a", org_name="org-a", number=1
    )
    b = await _make_chain(
        db, installation_id=_INSTALLATION_B, owner="owner-b", org_name="org-b", number=2
    )
    dev_a = await _make_user(db, "kc-dev-a")
    dev_b = await _make_user(db, "kc-dev-b")
    pa = await _make_user(db, "kc-pa", role="PLATFORM_ADMIN")
    none_user = await _make_user(db, "kc-none")
    db.add(OrgMember(org_id=a.org.id, user_id=dev_a.id, role="DEVELOPER"))
    db.add(OrgMember(org_id=b.org.id, user_id=dev_b.id, role="DEVELOPER"))
    db.add(OrgMember(org_id=a.org.id, user_id=none_user.id, role="DEVELOPER"))
    await db.commit()
    return SimpleNamespace(
        a=a, b=b, dev_a=dev_a, dev_b=dev_b, pa=pa, none_user=none_user
    )


class _GitHubStub:
    """Recording stand-in for the review_posting GitHub seams."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: Exception | None = None


def _patch_github(monkeypatch) -> _GitHubStub:
    stub = _GitHubStub()

    async def fake_post_pr_review(
        full_name, pr_number, commit_sha, body, installation_token
    ):
        stub.calls.append(
            {
                "full_name": full_name,
                "pr_number": pr_number,
                "commit_sha": commit_sha,
                "body": body,
                "installation_token": installation_token,
            }
        )
        if stub.error is not None:
            raise stub.error
        return 987654321

    async def fake_installation_token(installation_id):
        return "ghs_test_token"

    monkeypatch.setattr(
        "app.services.review_posting.post_pr_review", fake_post_pr_review
    )
    monkeypatch.setattr(
        "app.services.review_posting.get_installation_token",
        fake_installation_token,
    )
    return stub


def _comment_of(review, *, severity: str) -> ReviewComment:
    return next(c for c in review.comments if c.severity == severity)


# ---------------------------------------------------------------------------
# F3 retrofit: one cross-org test per endpoint
# ---------------------------------------------------------------------------


async def test_list_reviews_filters_to_member_orgs(client, stage):
    """GET /reviews: each member sees only their org's reviews."""
    dev_a = _auth("kc-dev-a")
    dev_b = _auth("kc-dev-b")

    resp_a = await client.get(f"{_REVIEWS}", headers=dev_a)
    resp_b = await client.get(f"{_REVIEWS}", headers=dev_b)
    assert resp_a.status_code == 200
    assert [r["id"] for r in resp_a.json()["items"]] == [str(stage.a.review.id)]

    assert resp_b.status_code == 200
    assert [r["id"] for r in resp_b.json()["items"]] == [str(stage.b.review.id)]


async def test_list_reviews_platform_admin_sees_all(client, stage):
    resp = await client.get(f"{_REVIEWS}", headers=_auth("kc-pa", ("PLATFORM_ADMIN",)))
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()["items"]}
    assert ids == {str(stage.a.review.id), str(stage.b.review.id)}


async def test_get_review_cross_org_is_404(client, stage):
    resp = await client.get(
        f"{_REVIEWS}/{stage.a.review.id}", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_status_cross_org_is_404(client, stage):
    resp = await client.get(
        f"{_REVIEWS}/{stage.a.review.id}/status", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_scan_report_cross_org_is_404(client, stage):
    resp = await client.get(
        f"{_REVIEWS}/{stage.a.review.id}/scan-report", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_retry_cross_org_is_404(client, stage):
    resp = await client.post(
        f"{_REVIEWS}/{stage.a.review.id}/retry", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_delete_cross_org_is_404(client, stage):
    resp = await client.delete(
        f"{_REVIEWS}/{stage.a.review.id}", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_resolve_cross_org_is_404(client, stage):
    """Cross-org 404s on the *review* guard — before any comment lookup."""
    comment = _comment_of(stage.a.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/resolve",
        headers=_auth("kc-dev-b"),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_get_pull_request_cross_org_is_404(client, stage):
    resp = await client.get(f"{_PRS}/{stage.a.pr.id}", headers=_auth("kc-dev-b"))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Pull request not found"


async def test_pull_request_reviews_cross_org_is_404(client, stage):
    resp = await client.get(
        f"{_PRS}/{stage.a.pr.id}/reviews", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Pull request not found"


async def test_trigger_review_cross_org_is_404(client, stage):
    resp = await client.post(
        f"{_PRS}/{stage.a.pr.id}/review", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Pull request not found"


async def test_summary_cross_org_is_404(client, stage):
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary",
        json={"summary": "hi"},
        headers=_auth("kc-dev-b"),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_dismiss_cross_org_is_404(client, stage):
    comment = _comment_of(stage.a.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/dismiss",
        headers=_auth("kc-dev-b"),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_restore_cross_org_is_404(client, stage):
    comment = _comment_of(stage.a.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/restore",
        headers=_auth("kc-dev-b"),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_post_cross_org_is_404(client, stage, monkeypatch):
    _patch_github(monkeypatch)
    resp = await client.post(
        f"{_REVIEWS}/{stage.a.review.id}/post", headers=_auth("kc-dev-b")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


# ---------------------------------------------------------------------------
# Guard matrix: NONE-first, F2 carve-out, malformed ids
# ---------------------------------------------------------------------------


async def test_none_is_403_on_every_staged_write_first(client, stage):
    """NONE-first: 403 before any membership/404 consideration."""
    headers = _auth("kc-none", ("NONE",))
    comment = _comment_of(stage.a.review, severity="error")

    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary",
        json={"summary": "x"},
        headers=headers,
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/dismiss",
        headers=headers,
    )
    assert resp.status_code == 403

    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 403


async def test_none_membership_still_reads(client, stage):
    """NONE is read-only, not invisible: the membership grants reads."""
    resp = await client.get(
        f"{_REVIEWS}/{stage.a.review.id}", headers=_auth("kc-none", ("NONE",))
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(stage.a.review.id)


async def test_platform_admin_reads_without_membership(client, stage):
    """F2: PLATFORM_ADMIN bypasses membership on reads."""
    headers = _auth("kc-pa", ("PLATFORM_ADMIN",))
    resp = await client.get(f"{_REVIEWS}/{stage.a.review.id}", headers=headers)
    assert resp.status_code == 200

    resp = await client.get(f"{_PRS}/{stage.a.pr.id}", headers=headers)
    assert resp.status_code == 200


async def test_platform_admin_cannot_touch_staged_state_without_membership(
    client, stage
):
    """F2 carve-out: summary/dismiss/restore/post need a membership row."""
    headers = _auth("kc-pa", ("PLATFORM_ADMIN",))
    comment = _comment_of(stage.a.review, severity="error")

    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary",
        json={"summary": "nope"},
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"

    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/dismiss",
        headers=headers,
    )
    assert resp.status_code == 404

    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 404


async def test_platform_admin_keeps_legacy_mutation_bypass(client, stage):
    """§3 retrofit row: retry/delete/resolve keep the read-style bypass."""
    headers = _auth("kc-pa", ("PLATFORM_ADMIN",))
    comment = _comment_of(stage.b.review, severity="info")

    resp = await client.patch(
        f"{_REVIEWS}/{stage.b.review.id}/comments/{comment.id}/resolve",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["resolved"] is True

    resp = await client.delete(f"{_REVIEWS}/{stage.b.review.id}", headers=headers)
    assert resp.status_code == 204


async def test_member_passes_legacy_mutations(client, stage):
    """Members still reach the legacy handlers after the retrofit."""
    headers = _auth("kc-dev-a")

    # Guard passes; the handler's own precondition fires (400, not 404/403).
    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/retry", headers=headers)
    assert resp.status_code == 400

    resp = await client.get(f"{_PRS}/{stage.a.pr.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(stage.a.pr.id)

    resp = await client.get(f"{_PRS}/{stage.a.pr.id}/reviews", headers=headers)
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()] == [str(stage.a.review.id)]


async def test_member_triggers_review(client, stage, monkeypatch):
    """POST /pull-requests/{id}/review still works for a member (F3)."""
    queued: list[str] = []

    async def fake_queue(review_id, **kwargs):
        queued.append(review_id)

    # NOTE: ``app.workers.review_queue`` as a *package attribute* is the
    # ``ReviewQueue`` singleton re-exported by ``app.workers.__init__`` —
    # patch the real module from sys.modules, where the route's local
    # ``from app.workers.review_queue import queue_review`` reads it.
    monkeypatch.setattr(
        import_module("app.workers.review_queue"), "queue_review", fake_queue
    )

    resp = await client.post(
        f"{_PRS}/{stage.a.pr.id}/review", headers=_auth("kc-dev-a")
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    assert len(queued) == 1


async def test_trigger_review_none_is_403(client, stage):
    resp = await client.post(
        f"{_PRS}/{stage.a.pr.id}/review", headers=_auth("kc-none", ("NONE",))
    )
    assert resp.status_code == 403


async def test_malformed_ids_are_404_not_500(client, stage):
    headers = _auth("kc-dev-a")
    resp = await client.get(f"{_REVIEWS}/not-a-uuid", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"

    resp = await client.get(f"{_PRS}/not-a-uuid", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Pull request not found"


# ---------------------------------------------------------------------------
# PATCH /reviews/{id}/summary
# ---------------------------------------------------------------------------


async def test_summary_happy_path_round_trips(client, stage):
    headers = _auth("kc-dev-a")
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary",
        json={"summary": "Edited **summary** for the panel."},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["edited_summary"] == "Edited **summary** for the panel."
    assert body["posted_at"] is None

    # The GET (what the Step 7b panel reads) exposes the staged state.
    resp = await client.get(f"{_REVIEWS}/{stage.a.review.id}", headers=headers)
    got = resp.json()
    assert got["edited_summary"] == "Edited **summary** for the panel."
    assert got["posting_mode"] == "staged"
    assert got["posted_at"] is None
    assert got["github_review_id"] is None


async def test_summary_over_cap_is_422(client, stage):
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary",
        json={"summary": "x" * (EDITED_SUMMARY_MAX_CHARS + 1)},
        headers=_auth("kc-dev-a"),
    )
    assert resp.status_code == 422


async def test_summary_requires_auth(client, stage):
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary", json={"summary": "x"}
    )
    assert resp.status_code == 401


async def test_summary_after_post_is_409(client, stage, monkeypatch):
    _patch_github(monkeypatch)
    headers = _auth("kc-dev-a")
    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 200

    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary",
        json={"summary": "too late"},
        headers=headers,
    )
    assert resp.status_code == 409
    assert "read-only" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH .../dismiss + .../restore
# ---------------------------------------------------------------------------


async def test_dismiss_and_restore_round_trip(client, stage):
    headers = _auth("kc-dev-a")
    comment = _comment_of(stage.a.review, severity="error")

    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/dismiss",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dismissed"] is True
    assert body["dismissed_by"] == str(stage.dev_a.id)
    assert body["dismissed_at"] is not None

    # Round-trips through GET for the panel.
    resp = await client.get(f"{_REVIEWS}/{stage.a.review.id}", headers=headers)
    shown = next(c for c in resp.json()["comments"] if c["id"] == str(comment.id))
    assert shown["dismissed"] is True
    assert shown["dismissed_by"] == str(stage.dev_a.id)

    # Idempotent state set (not a toggle): dismissing twice stays dismissed.
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/dismiss",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["dismissed"] is True

    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/restore",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["dismissed"] is False
    assert resp.json()["dismissed_by"] is None
    assert resp.json()["dismissed_at"] is None


async def test_reviewer_member_passes_developer_floor(client, stage, db):
    """Step 7 endpoints are DEVELOPER-floor: a REVIEWER member may trim.

    (The REVIEWER-only floor arrives with ``POST /validate`` in Step 9 —
    here the guard matrix only distinguishes NONE vs everyone else.)
    """
    reviewer = await _make_user(db, "kc-reviewer")
    db.add(OrgMember(org_id=stage.a.org.id, user_id=reviewer.id, role="REVIEWER"))
    await db.commit()

    comment = _comment_of(stage.a.review, severity="info")
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{comment.id}/dismiss",
        headers=_auth("kc-reviewer"),
    )
    assert resp.status_code == 200
    assert resp.json()["dismissed"] is True


async def test_dismiss_comment_not_in_review_is_404(client, stage):
    """Comment of another review, under this review's path → 404."""
    foreign = _comment_of(stage.b.review, severity="error")
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{foreign.id}/dismiss",
        headers=_auth("kc-dev-a"),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Comment not found"


async def test_resolve_comment_not_found_is_404(client, stage):
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{uuid.uuid4()}/resolve",
        headers=_auth("kc-dev-a"),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Comment not found"


# ---------------------------------------------------------------------------
# POST /reviews/{id}/post
# ---------------------------------------------------------------------------


async def test_post_success_marks_review_and_builds_staged_body(
    client, stage, monkeypatch
):
    """Happy path: posted_at + github_review_id set, body = base + findings."""
    stub = _patch_github(monkeypatch)
    headers = _auth("kc-dev-a")
    info = _comment_of(stage.a.review, severity="info")

    # The panel flow: edit summary, dismiss the noise, post.
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/summary",
        json={"summary": "Manual summary for staging."},
        headers=headers,
    )
    assert resp.status_code == 200
    resp = await client.patch(
        f"{_REVIEWS}/{stage.a.review.id}/comments/{info.id}/dismiss",
        headers=headers,
    )
    assert resp.status_code == 200

    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["github_review_id"] == 987654321
    assert body["posted_at"] is not None
    assert body["review_id"] == str(stage.a.review.id)

    # Persisted state is visible through GET.
    resp = await client.get(f"{_REVIEWS}/{stage.a.review.id}", headers=headers)
    got = resp.json()
    assert got["posted_at"] is not None
    assert got["github_review_id"] == 987654321
    assert got["error_message"] is None

    # The GitHub body: edited summary as base, Findings over the kept
    # comment only, sanitized (@mention neutralised, severity header).
    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert call["full_name"] == "owner-a/demo"
    assert call["pr_number"] == 1
    assert call["commit_sha"] == "b" * 40
    assert call["installation_token"] == "ghs_test_token"
    assert call["body"].startswith("Manual summary for staging.")
    assert "## Findings" in call["body"]
    assert "### error" in call["body"]
    assert "fix @alice" not in call["body"]
    assert "@\u200balice" in call["body"]
    assert _INFO_MSG not in call["body"]  # dismissed → excluded


async def test_post_twice_sequential_is_409(client, stage, monkeypatch):
    _patch_github(monkeypatch)
    headers = _auth("kc-dev-a")

    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 200

    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 409
    assert "already posted" in resp.json()["detail"]


async def test_post_concurrent_has_exactly_one_winner(client, stage, monkeypatch):
    """Two simultaneous posts: the FOR UPDATE lock serializes them (409)."""
    stub = _patch_github(monkeypatch)
    headers = _auth("kc-dev-a")
    url = f"{_REVIEWS}/{stage.a.review.id}/post"

    first, second = await asyncio.gather(
        client.post(url, headers=headers), client.post(url, headers=headers)
    )
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 409], statuses
    assert len(stub.calls) == 1  # GitHub saw exactly one POST


async def test_post_github_failure_is_retryable_502(client, stage, monkeypatch):
    stub = _patch_github(monkeypatch)
    headers = _auth("kc-dev-a")
    stub.error = ReviewPostError(422, "Validation Failed: bad sha")

    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "nothing was posted" in detail
    assert "422" in detail

    # Stored, not hidden: posted_at stays NULL, error_message persists.
    resp = await client.get(f"{_REVIEWS}/{stage.a.review.id}", headers=headers)
    got = resp.json()
    assert got["posted_at"] is None
    assert got["github_review_id"] is None
    assert "GitHub post failed (422)" in got["error_message"]

    # Retryable: fix the cause, post again → 200 and the error clears.
    stub.error = None
    resp = await client.post(f"{_REVIEWS}/{stage.a.review.id}/post", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["github_review_id"] == 987654321

    resp = await client.get(f"{_REVIEWS}/{stage.a.review.id}", headers=headers)
    assert resp.json()["error_message"] is None
    assert resp.json()["posted_at"] is not None


async def test_post_github_network_error_is_502(client, stage, monkeypatch):
    import httpx

    stub = _patch_github(monkeypatch)
    stub.error = httpx.ConnectError("connection refused")

    resp = await client.post(
        f"{_REVIEWS}/{stage.a.review.id}/post", headers=_auth("kc-dev-a")
    )
    assert resp.status_code == 502
    assert "nothing was posted" in resp.json()["detail"]


async def test_post_auto_mode_is_409(client, stage, db, monkeypatch):
    """Auto reviews are posted by the worker — the API refuses them."""
    _patch_github(monkeypatch)
    review = await db.get(Review, stage.a.review.id)
    review.posting_mode = "auto"
    await db.commit()

    resp = await client.post(
        f"{_REVIEWS}/{stage.a.review.id}/post", headers=_auth("kc-dev-a")
    )
    assert resp.status_code == 409
    assert "not staged" in resp.json()["detail"]


async def test_post_not_ready_is_409(client, stage, db, monkeypatch):
    _patch_github(monkeypatch)
    review = await db.get(Review, stage.a.review.id)
    review.status = "processing"
    await db.commit()

    resp = await client.post(
        f"{_REVIEWS}/{stage.a.review.id}/post", headers=_auth("kc-dev-a")
    )
    assert resp.status_code == 409
    assert "not ready to post" in resp.json()["detail"]


async def test_post_unknown_review_is_404(client, stage, monkeypatch):
    _patch_github(monkeypatch)
    resp = await client.post(
        f"{_REVIEWS}/{uuid.uuid4()}/post", headers=_auth("kc-dev-a")
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"
