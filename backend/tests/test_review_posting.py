"""Shared staged-posting body builder + poster (plan Step 6, Q3).

Covers ``app/services/review_posting.py``:

- auto mode: body = summary verbatim (byte-identical to the pre-release
  path — no findings, no sanitization, defensive GitHub-cap only);
- staged mode: sanitized base (hostile @mentions/#refs/links/HTML
  neutralized, ordinary markdown survives) + a ``## Findings`` section
  over non-dismissed comments grouped severity → file, truncated at
  GitHub's 65 536-char cap with the ``… N more findings, see CodeSage``
  closing line;
- ``post_review_to_github``: auto loads nothing extra (worker seam),
  staged refreshes comments and appends the section (API seam, Step 7).
"""

import re
import uuid
from datetime import datetime, timezone

from app.db.models import (
    GitHubInstallation,
    PullRequest,
    Repository,
    Review,
    ReviewComment,
)
from app.services import review_posting
from app.services.review_posting import (
    EDITED_SUMMARY_MAX_CHARS,
    GITHUB_BODY_MAX_CHARS,
    build_review_body,
    sanitize_generated_text,
)

HOSTILE = "@everyone [click](http://evil) #123 <script>alert(1)</script>"


def _comment(
    *,
    path="app/main.py",
    line=10,
    severity="error",
    body="Bad thing.",
    dismissed=False,
):
    return ReviewComment(
        file_path=path,
        line_number=line,
        severity=severity,
        category="general",
        body=body,
        dismissed=dismissed,
    )


def _review(
    *,
    summary="## Review\nLooks good.",
    edited=None,
    posting_mode="auto",
    comments=(),
):
    review = Review(
        pull_request_id=uuid.uuid4(),
        status="completed",
        started_at=datetime.now(timezone.utc),
        summary=summary,
        edited_summary=edited,
        posting_mode=posting_mode,
    )
    review.comments.extend(comments)
    return review


# --- auto mode: byte-identical -----------------------------------------------


def test_auto_body_is_summary_verbatim():
    """Auto mode posts the raw summary — no sanitization, no findings."""
    summary = "Raw @mention [x](y) #42 ## Head\n**bold**"
    review = _review(summary=summary)
    assert build_review_body(review, include_findings=False) == summary


def test_auto_body_prefers_edited_summary():
    review = _review(summary="original", edited="human rewrite")
    assert build_review_body(review, include_findings=False) == "human rewrite"


def test_auto_body_falls_back_to_empty_string():
    review = _review(summary=None)
    assert build_review_body(review, include_findings=False) == ""


def test_auto_body_defensive_cap():
    review = _review(summary="x" * (GITHUB_BODY_MAX_CHARS + 500))
    body = build_review_body(review, include_findings=False)
    assert len(body) == GITHUB_BODY_MAX_CHARS


# --- staged mode: sanitization (Q3 hostile string) ---------------------------


def test_staged_body_neutralizes_hostile_content():
    review = _review(summary=HOSTILE, posting_mode="staged", comments=[_comment()])
    body = build_review_body(review, include_findings=True)

    assert "@\u200beveryone" in body  # mention neutralized
    assert "\\[click\\]\\(http://evil\\)" in body  # link escaped, no raw "[click]("
    assert "[click](" not in body
    assert "#\u200b123" in body  # issue ref neutralized
    assert "<script>" not in body and "alert" in body  # tag stripped, text kept
    assert "## Findings" in body


def test_staged_body_keeps_ordinary_markdown():
    summary = "## Review\n\n**Bold** and `- code`\n\n- item one\n"
    review = _review(summary=summary, posting_mode="staged", comments=[_comment()])
    body = build_review_body(review, include_findings=True)

    assert "## Review" in body  # heading untouched (hash + space)
    assert "**Bold**" in body
    assert "`- code`" in body
    assert "- item one" in body


def test_sanitize_leaves_plain_text_and_headings_alone():
    text = "## Head\n- li\n**b**\n# 123 heading"
    assert sanitize_generated_text(text) == text


def test_sanitize_strips_tag_like_html_only():
    assert sanitize_generated_text("if a < b and c > d keep") == "if a < b and c > d keep"
    assert sanitize_generated_text("<b>hi</b>") == "hi"


# --- staged mode: findings section -------------------------------------------


def test_staged_findings_grouped_by_severity_then_file():
    comments = [
        _comment(path="b.py", line=2, severity="warning", body="W1"),
        _comment(path="z.py", line=30, severity="error", body="E2"),
        _comment(path="a.py", line=5, severity="error", body="E1"),
        _comment(path="a.py", line=1, severity="suggestion", body="S1"),
        _comment(path="a.py", line=9, severity="info", body="I1"),
        _comment(path="hidden.py", line=9, severity="error", body="Gone", dismissed=True),
    ]
    review = _review(posting_mode="staged", comments=comments)
    body = build_review_body(review, include_findings=True)

    assert "Gone" not in body  # dismissed findings never render
    # Group order: error > warning > suggestion > info.
    order = [
        body.index("### error"),
        body.index("### warning"),
        body.index("### suggestion"),
        body.index("### info"),
    ]
    assert order == sorted(order)
    # Within a severity: file/line order.
    assert body.index("`a.py:5`") < body.index("`z.py:30`")
    # Line format: `path:line` [tool] message (tool column lands in 015).
    assert "- `a.py:5` [codesage] E1" in body


def test_staged_body_without_findings_has_no_section():
    review = _review(
        posting_mode="staged",
        comments=[_comment(dismissed=True), _comment(body="still here")],
    )
    body = build_review_body(review, include_findings=True)
    # One active finding renders a section…
    assert "## Findings" in body

    review_all_dismissed = _review(
        posting_mode="staged", comments=[_comment(dismissed=True)]
    )
    # …while an empty set renders only the sanitized base.
    assert (
        "## Findings"
        not in build_review_body(review_all_dismissed, include_findings=True)
    )


def test_staged_findings_truncated_at_github_cap():
    comments = [
        _comment(path=f"f{i:04}.py", line=i, severity="error", body="X" * 180)
        for i in range(2_000)
    ]
    review = _review(posting_mode="staged", comments=comments)
    body = build_review_body(review, include_findings=True)

    assert len(body) <= GITHUB_BODY_MAX_CHARS
    match = re.search(r"… (\d+) more findings, see CodeSage", body)
    assert match is not None
    assert int(match.group(1)) > 0


def test_edited_summary_cap_constant():
    """PATCH /reviews/{id}/summary enforces this exact cap (Step 7)."""
    assert EDITED_SUMMARY_MAX_CHARS == 60_000


# --- Review.is_* properties (ready_to_post end-to-end) -----------------------


def test_review_status_properties():
    review = _review()
    review.status = "ready_to_post"
    assert review.is_ready_to_post is True
    assert review.is_posted is False

    review.github_review_id = 5
    assert review.is_posted is True

    review.status = "completed"
    assert review.is_ready_to_post is False
    assert review.is_completed is True


# --- post_review_to_github (shared entry point) ------------------------------


async def _chain(db, *, posting_mode):
    installation = GitHubInstallation(
        app_id=1,
        installation_id=111_222,
        account_id=1,
        account_login="o",
        account_type="User",
    )
    db.add(installation)
    await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=1,
        name="demo",
        full_name="o/demo",
    )
    db.add(repository)
    await db.flush()

    pr = PullRequest(
        repository_id=repository.id,
        github_pr_id=9,
        number=3,
        title="t",
        author_login="o",
        base_branch="main",
        head_branch="f",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    db.add(pr)
    await db.flush()

    review = Review(
        pull_request_id=pr.id,
        status="ready_to_post" if posting_mode == "staged" else "completed",
        posting_mode=posting_mode,
        summary="Plain summary.",
        started_at=datetime.now(timezone.utc),
    )
    db.add(review)
    await db.flush()

    db.add(
        ReviewComment(
            review_id=review.id,
            pull_request_id=pr.id,
            file_path="a.py",
            line_number=7,
            severity="error",
            category="security",
            body="RCE risk.",
        )
    )
    db.add(
        ReviewComment(
            review_id=review.id,
            pull_request_id=pr.id,
            file_path="b.py",
            line_number=1,
            severity="info",
            category="style",
            body="nitpick",
            dismissed=True,
        )
    )
    await db.commit()
    return pr, repository, review


async def test_post_review_to_github_staged_appends_findings(db, monkeypatch):
    """API seam (Step 7): staged post loads comments and adds the section."""
    _pr, _repository, review = await _chain(db, posting_mode="staged")

    recorded = {}

    async def fake_post(**kwargs):
        recorded.update(kwargs)
        return 4242

    async def fake_token(installation_id):
        return "tok"

    monkeypatch.setattr(review_posting, "post_pr_review", fake_post)
    monkeypatch.setattr(review_posting, "get_installation_token", fake_token)

    gh_id = await review_posting.post_review_to_github(db, review)

    assert gh_id == 4242
    assert recorded["full_name"] == "o/demo"
    assert recorded["pr_number"] == 3
    assert recorded["commit_sha"] == "b" * 40
    assert recorded["installation_token"] == "tok"

    body = recorded["body"]
    assert body.startswith("Plain summary.")
    assert "## Findings" in body
    assert "RCE risk." in body
    assert "nitpick" not in body  # dismissed excluded


async def test_post_review_to_github_auto_posts_plain_summary(db, monkeypatch):
    """Worker seam: auto mode never touches comments or findings."""
    pr, repository, review = await _chain(db, posting_mode="auto")

    recorded = {}

    async def fake_post(**kwargs):
        recorded.update(kwargs)
        return 7

    monkeypatch.setattr(review_posting, "post_pr_review", fake_post)

    gh_id = await review_posting.post_review_to_github(
        db, review, pr=pr, repo=repository, installation_token="tok"
    )

    assert gh_id == 7
    assert recorded["body"] == "Plain summary."  # verbatim, no findings
    assert "## Findings" not in recorded["body"]
