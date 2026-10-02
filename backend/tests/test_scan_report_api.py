"""GET /reviews/{review_id}/scan-report: auth, filters, error contract.

Reads the unified scan report persisted by the worker (tables 010/011):
401 without a token, 404 unknown review / no report yet, 422 invalid
filter vocabulary, strongest-first findings, summary always full.
"""

import uuid

from conftest import make_keycloak_token

from app.config import settings
from app.db.models import GitHubInstallation, PullRequest, Repository, Review
from app.services.normalizers import NormalizedFinding, ScanReport, ToolFailure
from app.services.scan_report_store import persist_scan_report

API = settings.API_V1_PREFIX

_HEADERS = {"Authorization": f"Bearer {make_keycloak_token()}"}


async def _seed_review(db, user) -> Review:
    installation = GitHubInstallation(
        app_id=1,
        installation_id=246810,
        account_id=1,
        account_login="test-owner",
        account_type="User",
    )
    db.add(installation)
    await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=555,
        name="demo",
        full_name="test-owner/demo",
    )
    db.add(repository)
    await db.flush()

    pull_request = PullRequest(
        repository_id=repository.id,
        github_pr_id=666,
        number=3,
        title="Change",
        author_login="test-owner",
        base_branch="main",
        head_branch="feature",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    db.add(pull_request)
    await db.flush()

    review = Review(
        pull_request_id=pull_request.id, user_id=user.id, status="completed"
    )
    db.add(review)
    await db.commit()  # visible to the app's own sessions (separate connection)
    return review


def _report(scan_id: str) -> ScanReport:
    return ScanReport(
        scan_id=scan_id,
        tools_run=["sonarqube", "semgrep"],
        tools_failed=[ToolFailure(tool="semgrep", error="timeout")],
        findings=[
            NormalizedFinding(
                tool="sonarqube",
                rule_id="python:S4502",
                title="injection",
                message="Possible code injection",
                severity="high",
                category="vulnerability",
                file_path="src/a.py",
                line_start=10,
                cwe=["CWE-95"],
                also_detected_by=["semgrep"],
                raw={"key": "AX1"},
            ),
            NormalizedFinding(
                tool="semgrep",
                rule_id="python.lang.security.audit.eval-detected",
                message="Detected eval().",
                severity="medium",
                category="vulnerability",
                file_path="src/a.py",
                line_start=10,
                references=["https://example.com/rule"],
                raw={"check_id": "python...eval-detected"},
            ),
            NormalizedFinding(
                tool="semgrep",
                rule_id="python.style.equality-as-str",
                message="Use .equals()",
                severity="info",
                category="best_practice",
                file_path="src/b.py",
                line_start=2,
                raw={},
            ),
        ],
    )


async def test_report_without_token_401(client, db, user):
    review = await _seed_review(db, user)
    resp = await client.get(f"{API}/reviews/{review.id}/scan-report")
    assert resp.status_code == 401


async def test_unknown_review_404(client):
    resp = await client.get(
        f"{API}/reviews/{uuid.uuid4()}/scan-report", headers=_HEADERS
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_review_without_report_404(client, db, user):
    review = await _seed_review(db, user)
    resp = await client.get(f"{API}/reviews/{review.id}/scan-report", headers=_HEADERS)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No scan report for this review"


async def test_full_report_strongest_first(client, db, user):
    review = await _seed_review(db, user)
    await persist_scan_report(db, review.id, _report("scan-full"))

    resp = await client.get(f"{API}/reviews/{review.id}/scan-report", headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["scan_id"] == "scan-full"
    assert body["review_id"] == str(review.id)
    assert body["tools_run"] == ["sonarqube", "semgrep"]
    assert body["tools_failed"] == [{"tool": "semgrep", "error": "timeout"}]
    assert body["summary"]["total"] == 3
    # Strongest first: high, medium, info.
    assert [f["severity"] for f in body["findings"]] == [
        "high",
        "medium",
        "info",
    ]
    # Round-tripped union fields.
    top = body["findings"][0]
    assert top["also_detected_by"] == ["semgrep"]
    assert top["cwe"] == ["CWE-95"]
    assert top["raw"] == {"key": "AX1"}
    assert body["findings"][1]["references"] == ["https://example.com/rule"]


async def test_tool_filter_narrows_findings_not_summary(client, db, user):
    review = await _seed_review(db, user)
    await persist_scan_report(db, review.id, _report("scan-tool"))

    resp = await client.get(
        f"{API}/reviews/{review.id}/scan-report?tool=semgrep",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert {f["tool"] for f in body["findings"]} == {"semgrep"}
    assert len(body["findings"]) == 2
    # Summary still describes the FULL scan.
    assert body["summary"]["total"] == 3


async def test_severity_filter(client, db, user):
    review = await _seed_review(db, user)
    await persist_scan_report(db, review.id, _report("scan-sev"))

    resp = await client.get(
        f"{API}/reviews/{review.id}/scan-report?severity=medium",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["findings"]) == 1
    assert body["findings"][0]["severity"] == "medium"


async def test_combined_filters(client, db, user):
    review = await _seed_review(db, user)
    await persist_scan_report(db, review.id, _report("scan-both"))

    resp = await client.get(
        f"{API}/reviews/{review.id}/scan-report?tool=semgrep&severity=info",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["findings"]) == 1
    assert body["findings"][0]["rule_id"] == "python.style.equality-as-str"


async def test_invalid_filters_422(client, db, user):
    review = await _seed_review(db, user)
    await persist_scan_report(db, review.id, _report("scan-bad"))

    resp = await client.get(
        f"{API}/reviews/{review.id}/scan-report?tool=clang-tidy",
        headers=_HEADERS,
    )
    assert resp.status_code == 422
    assert "Unknown tool" in resp.json()["detail"]

    resp = await client.get(
        f"{API}/reviews/{review.id}/scan-report?severity=catastrophic",
        headers=_HEADERS,
    )
    assert resp.status_code == 422
    assert "Unknown severity" in resp.json()["detail"]


async def test_latest_report_wins(client, db, user):
    review = await _seed_review(db, user)
    await persist_scan_report(db, review.id, _report("scan-first"))
    await persist_scan_report(db, review.id, _report("scan-second"))

    resp = await client.get(f"{API}/reviews/{review.id}/scan-report", headers=_HEADERS)

    assert resp.status_code == 200
    assert resp.json()["scan_id"] == "scan-second"
