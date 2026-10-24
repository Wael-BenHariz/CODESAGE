"""Dev-only local-review endpoint and validation-error sanitization."""

import copy

import pytest

from app.api.routes import local_reviews
from app.config import settings
from app.schemas.local_review import LocalReviewResult, LocalReviewStatistics

API = settings.API_V1_PREFIX
PATH = f"{API}/local-reviews/dev"
TOKEN = "test-local-review-token"

PAYLOAD = {
    "schema_version": 1,
    "snapshot": {
        "id": "snapshot-test-1",
        "head_sha": "a" * 40,
        "branch": "feature",
        "captured_at": "2026-01-01T00:00:00Z",
        "files": [
            {
                "path": "app.py",
                "status": "modified",
                "size": 9,
                "content_sha256": "b" * 64,
            }
        ],
    },
    "title": "Local changes on feature",
    "description": "local review",
    "diff": "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-print(1)\n+print(2)\n",
    "language": "python",
    "files": [
        {
            "path": "app.py",
            "status": "modified",
            "content": "print(2)\n",
            "content_sha256": "b" * 64,
        }
    ],
}


@pytest.fixture
def dev_mode(monkeypatch):
    monkeypatch.setattr(local_reviews.settings, "LOCAL_REVIEW_DEV_MODE", True)
    monkeypatch.setattr(local_reviews.settings, "LOCAL_REVIEW_DEV_TOKEN", TOKEN)
    return {"X-CodeSage-Dev-Token": TOKEN}


@pytest.fixture
def stub_run(monkeypatch):
    calls = []

    async def fake_run(request, db):
        calls.append(request.snapshot.id)
        return LocalReviewResult(
            snapshot=request.snapshot,
            summary="No high-confidence issues.",
            overall_severity="low",
            statistics=LocalReviewStatistics(
                files_reviewed=len(request.files), issues_found=0
            ),
        )

    monkeypatch.setattr(local_reviews, "_run", fake_run)
    return calls


async def test_dev_route_is_hidden_and_not_found_when_disabled(client, monkeypatch):
    monkeypatch.setattr(local_reviews.settings, "LOCAL_REVIEW_DEV_MODE", False)
    resp = await client.post(
        PATH, json=PAYLOAD, headers={"X-CodeSage-Dev-Token": TOKEN}
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not found"}


async def test_dev_route_requires_token(client, dev_mode):
    resp = await client.post(PATH, json=PAYLOAD)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid development token"

    bad = await client.post(
        PATH, json=PAYLOAD, headers={"X-CodeSage-Dev-Token": "wrong"}
    )
    assert bad.status_code == 401


async def test_dev_route_rejects_forwarded_requests(client, dev_mode):
    resp = await client.post(
        PATH,
        json=PAYLOAD,
        headers={**dev_mode, "X-Forwarded-For": "203.0.113.10"},
    )
    assert resp.status_code == 404


async def test_dev_route_returns_review_result(client, dev_mode, stub_run):
    resp = await client.post(PATH, json=PAYLOAD, headers=dev_mode)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == "No high-confidence issues."
    assert body["snapshot"]["id"] == "snapshot-test-1"
    assert body["statistics"] == {
        "files_reviewed": 1,
        "issues_found": 0,
        "by_severity": {},
        "by_category": {},
    }
    assert stub_run == ["snapshot-test-1"]


async def test_dev_route_enforces_configured_file_cap(client, dev_mode, monkeypatch):
    monkeypatch.setattr(local_reviews.settings, "LOCAL_REVIEW_DEV_MAX_FILES", 1)
    payload = copy.deepcopy(PAYLOAD)
    payload["snapshot"]["files"].append(
        {
            "path": "other.py",
            "status": "modified",
            "size": 9,
            "content_sha256": "c" * 64,
        }
    )
    payload["files"].append(
        {
            "path": "other.py",
            "status": "modified",
            "content": "print(3)\n",
            "content_sha256": "c" * 64,
        }
    )
    resp = await client.post(PATH, json=payload, headers=dev_mode)
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Too many files"


async def test_validation_errors_do_not_echo_input_body_or_ctx(client, dev_mode):
    payload = copy.deepcopy(PAYLOAD)
    payload["schema_version"] = 2
    payload["title"] = "SENSITIVE_SOURCE_MARKER"
    resp = await client.post(PATH, json=payload, headers=dev_mode)
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"error", "detail"}
    assert "SENSITIVE_SOURCE_MARKER" not in resp.text
    assert all(set(item) == {"loc", "msg", "type"} for item in body["detail"])
