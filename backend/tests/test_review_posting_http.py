"""Tests for the GitHub review POST layer and post_review row guards.

The shared worker/API posting flow (post_review_to_github) is covered
end-to-end by tests/test_review_posting.py; these cover the HTTP
transport function (post_pr_review), the ValueError guards when the
PR/repo/installation rows are missing, and two small formatter gaps
(empty sanitization input, long-message truncation).
"""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.services.review_posting import (
    SHORT_MESSAGE_CHARS,
    ReviewPostError,
    _finding_line,
    post_pr_review,
    post_review_to_github,
    sanitize_generated_text,
)

# Captured before any monkeypatching — after patching, httpx.AsyncClient
# *is* the factory, so the factory must not construct through that name.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_http(monkeypatch, responder):
    def factory(*args, **kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(responder))

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# --- post_pr_review (GitHub transport) --------------------------------------


async def test_post_pr_review_success(monkeypatch):
    seen = {}

    def responder(request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(201, json={"id": 4242})

    _patch_http(monkeypatch, responder)
    github_id = await post_pr_review(
        "owner/repo", 7, "abc123", "summary body", "ghs_token"
    )
    assert github_id == 4242
    assert seen["url"] == "https://api.github.com/repos/owner/repo/pulls/7/reviews"
    assert seen["payload"] == {
        "commit_id": "abc123",
        "body": "summary body",
        "event": "COMMENT",
    }
    assert seen["auth"] == "token ghs_token"


async def test_post_pr_review_github_rejection(monkeypatch):
    _patch_http(monkeypatch, lambda r: httpx.Response(401, text="Bad credentials"))
    with pytest.raises(ReviewPostError) as excinfo:
        await post_pr_review("owner/repo", 7, "abc123", "body", "bad-token")
    assert excinfo.value.status_code == 401
    assert "Bad credentials" in excinfo.value.detail


# --- post_review_to_github row guards ---------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    def __init__(self, *values):
        self._values = list(values)

    async def execute(self, *_args, **_kwargs):
        value = self._values.pop(0) if self._values else None
        return _FakeResult(value)


async def test_post_review_missing_pull_request_raises():
    review = SimpleNamespace(pull_request_id=uuid4(), posting_mode="auto")
    with pytest.raises(ValueError, match="Pull request not found"):
        await post_review_to_github(_FakeDb(), review)


async def test_post_review_missing_repository_raises():
    review = SimpleNamespace(pull_request_id=uuid4(), posting_mode="auto")
    pr = SimpleNamespace(id=uuid4(), repository_id=uuid4())
    with pytest.raises(ValueError, match="Repository not found"):
        await post_review_to_github(_FakeDb(pr), review)


async def test_post_review_missing_installation_raises():
    review = SimpleNamespace(posting_mode="auto")
    pr = SimpleNamespace(id=uuid4(), repository_id=uuid4())
    repo = SimpleNamespace(installation=None)
    with pytest.raises(ValueError, match="GitHub App installation not found"):
        await post_review_to_github(_FakeDb(), review, pr=pr, repo=repo)


# --- formatter gaps ---------------------------------------------------------


def test_sanitize_empty_text_is_passthrough():
    assert sanitize_generated_text("") == ""


def test_finding_line_truncates_long_messages():
    long_msg = "x" * (SHORT_MESSAGE_CHARS + 80)
    comment = SimpleNamespace(file_path="a.py", line_number=3, tool=None, body=long_msg)
    line = _finding_line(comment)
    assert line.startswith("- `a.py:3` [codesage] ")
    assert line.endswith("…")
    message = line.split("] ", 1)[1]
    assert len(message) == SHORT_MESSAGE_CHARS
