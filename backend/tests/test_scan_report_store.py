"""persist_scan_report / finding_from_row: write + read round-trip.

The persistence contract the worker depends on: one commit writes the
header + every finding row (including the cross-tool merge annotations),
and a broken insert RAISES so the worker can log + roll back without
failing the review.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    GitHubInstallation,
    PullRequest,
    Repository,
    Review,
    ScanFindingRow,
    ScanReportRow,
)
from app.services.normalizers import NormalizedFinding, ScanReport, ToolFailure
from app.services.scan_report_store import (
    finding_from_row,
    persist_scan_report,
)


async def _seed_review(db, user) -> Review:
    installation = GitHubInstallation(
        app_id=1,
        installation_id=424242,
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
        number=7,
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
    await db.flush()
    return review


def _report() -> ScanReport:
    return ScanReport(
        scan_id=uuid.uuid4().hex,
        tools_run=["sonarqube", "semgrep"],
        tools_failed=[ToolFailure(tool="semgrep", error="boom")],
        findings=[
            NormalizedFinding(
                tool="sonarqube",
                rule_id="python:S4502",
                title="injection",
                message="Possible code injection",
                severity="low",
                category="vulnerability",
                file_path="src/a.py",
                line_start=10,
                line_end=12,
                snippet="eval(x)",
                cwe=["CWE-95"],
                owasp=["A03:2021 - Injection"],
                references=["https://example.com/r"],
                also_detected_by=["semgrep"],
                fix_suggestion="use ast.literal_eval",
                raw={"key": "AX1"},
            ),
            NormalizedFinding(
                tool="semgrep",
                rule_id="python.lang.security.audit.eval-detected",
                message="Detected eval().",
                severity="high",
                category="vulnerability",
                file_path="src/b.py",
                line_start=4,
                raw={"check_id": "python.lang.security.audit.eval-detected"},
            ),
        ],
    )


async def test_round_trip_preserves_every_field(db, user):
    review = await _seed_review(db, user)
    report = _report()

    row = await persist_scan_report(db, review.id, report)

    # Fresh read — no identity-map shortcuts.
    stored = (
        await db.execute(
            select(ScanReportRow)
            .where(ScanReportRow.id == row.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert stored.scan_id == report.scan_id
    assert stored.tools_run == ["sonarqube", "semgrep"]
    assert stored.tools_failed == [{"tool": "semgrep", "error": "boom"}]
    assert stored.summary == report.summary

    findings = (
        (
            await db.execute(
                select(ScanFindingRow)
                .where(ScanFindingRow.report_id == row.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert len(findings) == 2
    by_tool = {f.tool: f for f in findings}

    sonar = finding_from_row(by_tool["sonarqube"])
    assert sonar.id == report.findings[0].id  # fingerprint survives the trip
    assert sonar.also_detected_by == ["semgrep"]  # merge annotation (011)
    assert sonar.snippet == "eval(x)"
    assert sonar.line_end == 12
    assert sonar.fix_suggestion == "use ast.literal_eval"
    assert sonar.cwe == ["CWE-95"]
    assert sonar.references == ["https://example.com/r"]
    assert sonar.raw == {"key": "AX1"}

    semgrep = finding_from_row(by_tool["semgrep"])
    assert semgrep.also_detected_by == []
    assert semgrep.owasp == [] and semgrep.references == []
    assert semgrep.severity == "high"


async def test_empty_report_persists_header_only(db, user):
    review = await _seed_review(db, user)
    report = ScanReport(scan_id="s-empty", tools_run=[], findings=[])

    row = await persist_scan_report(db, review.id, report)

    stored = (
        await db.execute(select(ScanReportRow).where(ScanReportRow.id == row.id))
    ).scalar_one()
    assert stored.summary["total"] == 0
    findings = (
        (
            await db.execute(
                select(ScanFindingRow).where(ScanFindingRow.report_id == row.id)
            )
        )
        .scalars()
        .all()
    )
    assert list(findings) == []


async def test_insert_failure_raises_and_transaction_recovers(db, user):
    """A bad review_id must raise (FK) — the worker logs + rolls back."""
    report = _report()

    with pytest.raises(IntegrityError):
        await persist_scan_report(db, uuid.uuid4(), report)

    # The session must be usable again after the worker-style rollback
    # (rollback expires the fixture row — refresh it before reuse).
    await db.rollback()
    await db.refresh(user)
    review = await _seed_review(db, user)
    row = await persist_scan_report(db, review.id, report)
    assert row.id is not None
