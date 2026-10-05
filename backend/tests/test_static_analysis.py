"""run_static_analysis: parallel execution + fault isolation + merge.

Both tools are stubbed at the module boundary (``sonarqube_service`` /
``SemgrepClient``); the tar.gz upload payload, normalization, merge, and
report assembly run for real.
"""

import asyncio
import copy
import time
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import static_analysis
from app.services.semgrep import SemgrepError
from app.services.sonarqube import SonarIssue, SonarQubeError

FILES = [{"filename": "src/a.py", "content": "x = 1\n"}]


def _sonar_issue() -> SonarIssue:
    return SonarIssue(
        key="AX1",
        rule="python:S4502",
        severity="MINOR",
        type="VULNERABILITY",
        component="src/a.py",
        line=10,
        message="Possible code injection.",
        effort="5min",
        tags=["external/cwe/cwe-95", "owasp2021-a03-injection"],
    )


SONAR_GROUPS = {"security": [_sonar_issue()]}

# Same file + same line + same CWE (CWE-95) as the sonar issue — the
# merge must fold it into ONE finding with also_detected_by=["semgrep"].
SEMGREP_REPORT = {
    "version": "1.178.0",
    "results": [
        {
            "check_id": (
                "semgrep-rules.python.lang.security.audit."
                "eval-detected.eval-detected"
            ),
            "path": "src/a.py",
            "start": {"line": 10, "col": 1},
            "end": {"line": 10, "col": 20},
            "extra": {
                "message": "Detected eval().",
                "lines": "eval(payload)",
                "metadata": {
                    "category": "security",
                    "cwe": ["CWE-95: Eval Injection"],
                    "owasp": ["A03:2021 - Injection"],
                    "references": ["https://example.com/rule"],
                },
                "severity": "ERROR",
            },
        }
    ],
    "errors": [],
}


@pytest.fixture
def sonar_stub(monkeypatch):
    """Replace SonarQube with a recording stub."""
    state = SimpleNamespace(calls=0, delay=0.0, outcome=None)

    async def scan(**kwargs):
        state.calls += 1
        if state.delay:
            await asyncio.sleep(state.delay)
        if state.outcome is not None:
            raise state.outcome
        return SONAR_GROUPS

    monkeypatch.setattr(
        static_analysis, "sonarqube_service", SimpleNamespace(scan=scan)
    )
    return state


@pytest.fixture
def semgrep_stub(monkeypatch):
    """Replace the Semgrep client with a recording stub.

    Verifies the real tar.gz upload payload exists while called.
    ``state.report`` is what the stub returns — tests may replace it to
    simulate service output shapes (e.g. the live absolute paths).
    """
    state = SimpleNamespace(calls=0, delay=0.0, outcome=None, report=SEMGREP_REPORT)

    class StubClient:
        async def async_scan(self, archive, **kwargs):
            state.calls += 1
            if state.delay:
                await asyncio.sleep(state.delay)
            if state.outcome is not None:
                raise state.outcome
            assert archive.exists() and archive.stat().st_size > 0
            return state.report

    monkeypatch.setattr(static_analysis, "SemgrepClient", StubClient)
    return state


def _run(**kwargs):
    kwargs.setdefault("review_id", "r-1")
    kwargs.setdefault("project_key", "codesage-review-deadbeef")
    kwargs.setdefault("files", FILES)
    kwargs.setdefault("language", "python")
    return static_analysis.run_static_analysis(**kwargs)


# --- parallelism -------------------------------------------------------------


async def test_both_tools_run_concurrently(sonar_stub, semgrep_stub):
    sonar_stub.delay = semgrep_stub.delay = 0.25

    started = time.monotonic()
    result = await _run()
    elapsed = time.monotonic() - started

    assert sonar_stub.calls == 1 and semgrep_stub.calls == 1
    # Sequential would take >= 0.50s; parallel ~0.25s + overhead.
    assert elapsed < 0.40, f"scans did not run in parallel ({elapsed:.2f}s)"
    assert result.report.tools_run == ["sonarqube", "semgrep"]
    assert result.report.tools_failed == []


# --- merged findings ---------------------------------------------------------


async def test_findings_are_normalized_and_merged(sonar_stub, semgrep_stub):
    result = await _run()

    findings = result.report.findings
    # Sonar issue + semgrep finding share file/line/CWE-95 -> one row.
    assert len(findings) == 1
    survivor = findings[0]
    assert survivor.tool == "sonarqube"
    assert survivor.also_detected_by == ["semgrep"]
    # Sonar MINOR -> low; semgrep ERROR -> high: survivor strengthened.
    assert survivor.severity == "high"
    assert survivor.cwe == ["CWE-95"]
    assert result.report.summary == {
        "total": 1,
        "by_severity": {"high": 1},
        "by_tool": {"sonarqube": 1},
    }
    assert result.report.scan_id  # non-empty, unique per run
    assert result.sonar_error is None and result.semgrep_error is None
    assert result.both_failed is False
    # Groups stay on the result for observability; the agents now consume
    # report.findings instead (Step 6).
    assert result.sonar_groups == SONAR_GROUPS


# --- snippet enrichment (Step 6) ----------------------------------------------


async def test_snippets_enriched_from_workspace(sonar_stub, semgrep_stub):
    files = [
        {"filename": "src/a.py", "content": "\n".join(f"L{i}" for i in range(1, 31))}
    ]
    result = await _run(files=files)

    (finding,) = result.report.findings
    lines = finding.snippet.splitlines()
    # Merged finding sits at line 10 -> ±10 lines, numbered from the file.
    assert lines[0] == "1: L1"
    assert lines[-1] == "20: L20"
    assert len(lines) == 20


async def test_scan_ids_are_unique_per_run(sonar_stub, semgrep_stub):
    first = await _run()
    second = await _run()
    assert first.report.scan_id != second.report.scan_id


async def test_live_service_output_is_reconciled_before_merge(sonar_stub, semgrep_stub):
    """Regression seen against the DEPLOYED service: semgrep reports
    absolute per-request temp paths (``/tmp/semgrep-scan-…/src/src/a.py``)
    and a two-segment check_id prefix (``opt.semgrep-rules.``). Without
    reconciliation the path never matches the workspace, so the merge
    never fires and snippets never enrich — silently.
    """
    live = copy.deepcopy(SEMGREP_REPORT)
    live["results"][0]["path"] = "/tmp/semgrep-scan-x7y8/src/src/a.py"
    live["results"][0]["check_id"] = "opt." + SEMGREP_REPORT["results"][0]["check_id"]
    # Second live-shaped finding (different line + CWE): stays separate,
    # so its semgrep-side rule id remains observable after the merge.
    second = copy.deepcopy(SEMGREP_REPORT["results"][0])
    second["path"] = live["results"][0]["path"]
    second["check_id"] = (
        "opt.semgrep-rules.python.lang.security.deserialization.pickle" ".avoid-pickle"
    )
    second["start"] = {"line": 20, "col": 1}
    second["end"] = {"line": 20, "col": 20}
    second["extra"]["message"] = "Detected pickle.loads()."
    second["extra"]["metadata"] = {"cwe": ["CWE-502: Deserialization of data"]}
    live["results"].append(second)
    semgrep_stub.report = live

    files = [
        {"filename": "src/a.py", "content": "\n".join(f"L{i}" for i in range(1, 31))}
    ]
    result = await _run(files=files)

    # Sonar issue + eval finding = ONE row despite the path dialect gap
    # (same file + line + CWE-95); the pickle finding stays its own row.
    assert len(result.report.findings) == 2
    survivor = result.report.findings[0]
    assert survivor.file_path == "src/a.py"  # reconciled, not the /tmp path
    assert survivor.tool == "sonarqube"  # primary tool keeps its rule id
    assert survivor.rule_id == "python:S4502"
    assert survivor.also_detected_by == ["semgrep"]
    # Snippet enrichment found the file through the reconciled path.
    lines = survivor.snippet.splitlines()
    assert lines[0] == "1: L1"
    assert lines[-1] == "20: L20"
    assert len(lines) == 20

    pickle_finding = result.report.findings[1]
    assert pickle_finding.tool == "semgrep"
    assert pickle_finding.file_path == "src/a.py"
    # Two-segment config prefix stripped all the way to the namespace.
    assert pickle_finding.rule_id == (
        "python.lang.security.deserialization.pickle.avoid-pickle"
    )
    assert pickle_finding.cwe == ["CWE-502"]
    pickle_lines = pickle_finding.snippet.splitlines()
    assert pickle_lines[0] == "10: L10"  # line 20 ±10 inside a 30-line file
    assert pickle_lines[-1] == "30: L30"


# --- fault isolation ---------------------------------------------------------


async def test_semgrep_failure_keeps_sonar_results(sonar_stub, semgrep_stub):
    semgrep_stub.outcome = SemgrepError("HTTP 504: scan timed out")

    result = await _run()

    assert result.report.tools_run == ["sonarqube"]
    assert [f.tool for f in result.report.tools_failed] == ["semgrep"]
    assert "HTTP 504" in result.report.tools_failed[0].error
    assert result.semgrep_error.startswith("Semgrep scan failed")
    assert result.sonar_error is None
    assert result.both_failed is False
    assert len(result.report.findings) == 1  # sonar finding survives


async def test_sonar_failure_keeps_semgrep_results(sonar_stub, semgrep_stub):
    sonar_stub.outcome = SonarQubeError("SonarQube API unreachable")

    result = await _run()

    assert result.report.tools_run == ["semgrep"]
    assert [f.tool for f in result.report.tools_failed] == ["sonarqube"]
    assert result.sonar_error.startswith("SonarQube scan failed")
    assert result.semgrep_error is None
    assert result.both_failed is False
    # Agents fall back to empty groups (pre-Semgrep behaviour kept).
    assert result.sonar_groups == {}
    (finding,) = result.report.findings
    assert finding.tool == "semgrep"


async def test_both_tools_failing_fails_only_the_stage(sonar_stub, semgrep_stub):
    sonar_stub.outcome = SonarQubeError("down")
    semgrep_stub.outcome = SemgrepError("unreachable after 3 attempt(s)")

    result = await _run()

    # The stage failed: nothing ran, nothing to show — but only the
    # stage: run_static_analysis never raises (the review never fails).
    assert result.report.tools_run == []
    assert sorted(f.tool for f in result.report.tools_failed) == [
        "semgrep",
        "sonarqube",
    ]
    assert result.report.findings == []
    assert result.report.summary["total"] == 0
    assert result.sonar_error and result.semgrep_error
    assert result.both_failed is True


async def test_unexpected_exception_is_still_isolated(sonar_stub, semgrep_stub):
    sonar_stub.outcome = RuntimeError("bug in scanner")
    semgrep_stub.outcome = ValueError("unexpected")

    result = await _run()

    assert result.both_failed is True
    assert "RuntimeError" in result.sonar_error or "bug" in result.sonar_error
    assert result.report.findings == []


# --- switches and preconditions ----------------------------------------------


async def test_disabled_semgrep_is_skipped_not_failed(
    sonar_stub, semgrep_stub, monkeypatch
):
    monkeypatch.setattr(settings, "SEMGREP_ENABLED", False)

    result = await _run()

    assert semgrep_stub.calls == 0  # never even started
    assert result.report.tools_run == ["sonarqube"]
    assert result.report.tools_failed == []
    assert result.semgrep_error is None
    assert result.both_failed is False
    assert len(result.report.findings) == 1


async def test_empty_files_skip_both_tools_without_failure(sonar_stub, semgrep_stub):
    result = await _run(files=[])

    assert sonar_stub.calls == 0 and semgrep_stub.calls == 0
    # Precondition note (kept verbatim from the sonar-only era), but no
    # tool is marked failed — nothing was attempted.
    assert result.sonar_error == ("SonarQube scan skipped: no fetchable file contents")
    assert result.semgrep_error is None
    assert result.report.tools_run == []
    assert result.report.tools_failed == []
    assert result.both_failed is False
