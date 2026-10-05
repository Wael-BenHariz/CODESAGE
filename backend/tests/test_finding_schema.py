"""Unified finding schema (NormalizedFinding / ScanReport) + persistence.

Covers: stable fingerprints, severity/category validation, automatic
report summaries, JSON round-trips, and the scan_reports/scan_findings
ORM mapping created by migration 010.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.db.models import (
    GitHubInstallation,
    PullRequest,
    Repository,
    Review,
    ScanFindingRow,
    ScanReportRow,
)
from app.services.normalizers import (
    NormalizedFinding,
    ScanReport,
    ToolFailure,
    fingerprint,
)

# --- fingerprint ------------------------------------------------------------


def test_fingerprint_is_stable():
    a = fingerprint(
        "semgrep", "python.lang.security.audit.eval", "app.py", 12, "eval used"
    )
    b = fingerprint(
        "semgrep", "python.lang.security.audit.eval", "app.py", 12, "eval used"
    )
    assert a == b
    assert len(a) == 40  # sha1 hex


def test_fingerprint_changes_with_each_field():
    base = ("sonarqube", "python:S555", "app.py", 3, "unsafe")
    base_id = fingerprint(*base)
    assert fingerprint("semgrep", *base[1:]) != base_id
    assert fingerprint(base[0], "other:rule", *base[2:]) != base_id
    assert fingerprint(*[base[0], base[1], "lib.py", *base[3:]]) != base_id
    assert fingerprint(*[base[0], base[1], base[2], 4, base[4]]) != base_id
    assert fingerprint(*[base[0], base[1], base[2], base[3], "safe"]) != base_id


def test_fingerprint_field_separator_prevents_collisions():
    # Concatenation tricks must not collide: "ab"+"c" != "a"+"bc"
    assert fingerprint("t", "ab", "c", None, "m") != fingerprint(
        "t", "a", "bc", None, "m"
    )


# --- NormalizedFinding ------------------------------------------------------


def test_finding_computes_id_when_empty():
    f = NormalizedFinding(tool="semgrep", rule_id="r1", file_path="a.py", message="m")
    assert f.id == fingerprint("semgrep", "r1", "a.py", None, "m")


def test_finding_keeps_explicit_id():
    f = NormalizedFinding(tool="sonarqube", id="custom", message="m")
    assert f.id == "custom"


def test_finding_rejects_unknown_severity():
    with pytest.raises(ValidationError):
        NormalizedFinding(tool="sonarqube", message="m", severity="blocker")


def test_finding_rejects_unknown_category():
    with pytest.raises(ValidationError):
        NormalizedFinding(tool="sonarqube", message="m", category="smell")


def test_finding_rejects_unknown_tool():
    with pytest.raises(ValidationError):
        NormalizedFinding(tool="flake8", message="m")


def test_finding_round_trips_raw_payload():
    f = NormalizedFinding(
        tool="sonarqube",
        rule_id="java:S2077",
        title="SQL injection",
        message="Parameterized queries required",
        severity="high",
        category="vulnerability",
        file_path="src/UserDao.java",
        line_start=42,
        line_end=44,
        cwe=["CWE-89"],
        owasp=["A03:2021-Injection"],
        references=["https://owasp.org"],
        fix_suggestion="Use PreparedStatement",
        raw={"key": "AX", "type": "VULNERABILITY"},
    )
    again = NormalizedFinding.model_validate(f.model_dump())
    assert again == f
    assert again.raw["key"] == "AX"
    assert again.id == f.id  # fingerprint survives the round-trip


# --- ScanReport -------------------------------------------------------------


def _finding(tool: str, severity: str, file_path: str = "a.py") -> NormalizedFinding:
    return NormalizedFinding(
        tool=tool,  # type: ignore[arg-type]
        rule_id="r",
        message=f"msg {tool} {severity}",
        severity=severity,  # type: ignore[arg-type]
        file_path=file_path,
    )


def test_scan_report_computes_summary():
    report = ScanReport(
        scan_id="s1",
        tools_run=["sonarqube", "semgrep"],
        findings=[
            _finding("sonarqube", "high"),
            _finding("sonarqube", "low"),
            _finding("semgrep", "high", "b.py"),
        ],
    )
    assert report.summary["total"] == 3
    assert report.summary["by_severity"] == {"high": 2, "low": 1}
    assert report.summary["by_tool"] == {"sonarqube": 2, "semgrep": 1}


def test_scan_report_keeps_explicit_summary():
    report = ScanReport(scan_id="s1", summary={"total": 99})
    assert report.summary["total"] == 99


def test_scan_report_records_tool_failures():
    report = ScanReport(
        scan_id="s2",
        tools_run=["sonarqube"],
        tools_failed=[ToolFailure(tool="semgrep", error="timeout")],
        findings=[_finding("sonarqube", "medium")],
    )
    assert report.tools_failed[0].error == "timeout"
    assert report.summary["by_tool"] == {"sonarqube": 1}


def test_scan_report_round_trip():
    report = ScanReport(
        scan_id="s3",
        tools_run=["semgrep"],
        findings=[_finding("semgrep", "critical")],
    )
    again = ScanReport.model_validate(report.model_dump())
    assert again.findings == report.findings
    assert again.summary == report.summary


# --- persistence (migration 010 / ORM mapping) ------------------------------


async def test_scan_report_and_findings_persist(db, user):
    installation = GitHubInstallation(
        app_id=1,
        installation_id=555,
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
        status="completed",
        started_at=datetime.now(timezone.utc),
    )
    db.add(review)
    await db.flush()

    report = ScanReport(
        scan_id="scan-abc",
        tools_run=["sonarqube", "semgrep"],
        tools_failed=[ToolFailure(tool="semgrep", error="boom")],
        findings=[
            _finding("sonarqube", "high", "src/App.java"),
            _finding("semgrep", "critical", "src/App.java"),
        ],
    )

    report_row = ScanReportRow(
        review_id=review.id,
        scan_id=report.scan_id,
        tools_run=report.tools_run,
        tools_failed=[f.model_dump() for f in report.tools_failed],
        summary=report.summary,
    )
    db.add(report_row)
    await db.flush()

    for finding in report.findings:
        db.add(
            ScanFindingRow(
                report_id=report_row.id,
                fingerprint=finding.id,
                tool=finding.tool,
                rule_id=finding.rule_id,
                title=finding.title,
                message=finding.message,
                severity=finding.severity,
                category=finding.category,
                file_path=finding.file_path,
                line_start=finding.line_start,
                cwe=finding.cwe or None,
                owasp=finding.owasp or None,
                reference_urls=finding.references or None,
                raw=finding.raw,
            )
        )
    await db.commit()

    # Read back through fresh statements.
    from sqlalchemy import select

    loaded = (
        await db.execute(
            select(ScanReportRow).where(ScanReportRow.review_id == review.id)
        )
    ).scalar_one()
    assert loaded.scan_id == "scan-abc"
    assert loaded.tools_run == ["sonarqube", "semgrep"]
    assert loaded.tools_failed == [{"tool": "semgrep", "error": "boom"}]
    assert loaded.summary["total"] == 2

    findings = (
        (
            await db.execute(
                select(ScanFindingRow)
                .where(ScanFindingRow.report_id == loaded.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert len(findings) == 2
    tools = {f.tool for f in findings}
    assert tools == {"sonarqube", "semgrep"}
    sonar = next(f for f in findings if f.tool == "sonarqube")
    assert sonar.severity == "high"
    assert sonar.fingerprint == report.findings[0].id
