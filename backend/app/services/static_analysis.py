"""Parallel static analysis: SonarQube + Semgrep over one file workspace.

Both tools scan the SAME full file contents (fetched at the PR head sha)
concurrently via ``asyncio.gather``. Each tool is independently
fault-isolated:

- a tool that fails or times out contributes nothing, is recorded in
  ``report.tools_failed`` and surfaces as a note in
  ``review.error_message`` — the review itself never fails because of
  either tool (hard constraint, brief A7.3);
- the stage counts as failed only when BOTH tools fail (logged loudly,
  findings empty);
- ``SEMGREP_ENABLED=false`` removes Semgrep from the run entirely —
  neither ``tools_run`` nor ``tools_failed`` (disabled != broken).

SonarQube's grouped output stays available on the result for
observability. The unified findings — normalized, cross-tool merged, and
snippet-enriched with ±10 lines of source from the workspace — come back
as a ready-to-persist ``ScanReport``; those findings (not the raw groups)
are what the specialist agents consume.
"""

import asyncio
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.services.normalizers import (
    ScanReport,
    ToolFailure,
    enrich_snippets,
    merge_findings,
    normalize_semgrep,
    normalize_sonar,
)
from app.services.semgrep import SemgrepClient, SemgrepError, build_scan_archive
from app.services.sonarqube import SonarIssue, SonarQubeError, sonarqube_service

logger = logging.getLogger(__name__)

_EMPTY_SONAR_GROUPS: dict[str, list[SonarIssue]] = {}


@dataclass
class ToolOutcome:
    """One tool's scan result: value, human note, and real-failure flag.

    ``failed=False`` with a note means the tool was skipped by
    precondition (no files) or disabled — not broken.
    """

    value: dict | None = None
    error: str | None = None
    failed: bool = False


@dataclass
class StaticAnalysisResult:
    """Outcome of the parallel scan pass."""

    sonar_groups: dict[str, list[SonarIssue]]
    report: ScanReport
    sonar_error: str | None = None
    semgrep_error: str | None = None
    both_failed: bool = field(default=False)


async def _run_sonar(project_key: str, files: list[dict], language: str) -> ToolOutcome:
    try:
        groups = await sonarqube_service.scan(
            project_key=project_key, files=files, language=language
        )
    except SonarQubeError as exc:
        return ToolOutcome(None, f"SonarQube scan failed: {exc}", failed=True)
    except Exception as exc:
        logger.exception("Unexpected SonarQube scan failure")
        return ToolOutcome(None, f"SonarQube scan failed: {exc!r}", failed=True)
    return ToolOutcome(groups)


async def _run_semgrep(files: list[dict]) -> ToolOutcome:
    if not settings.SEMGREP_ENABLED:
        return ToolOutcome()  # disabled: not run, not failed, no note

    try:
        with tempfile.TemporaryDirectory(prefix="semgrep-scan-") as tmp:
            archive = Path(tmp) / "sonar_files.tar.gz"
            if build_scan_archive(files, archive) == 0:
                return ToolOutcome()  # nothing scannable (precondition)
            report = await SemgrepClient().async_scan(archive)
    except SemgrepError as exc:
        return ToolOutcome(None, f"Semgrep scan failed: {exc}", failed=True)
    except Exception as exc:
        logger.exception("Unexpected Semgrep scan failure")
        return ToolOutcome(None, f"Semgrep scan failed: {exc!r}", failed=True)
    return ToolOutcome(report)


def _build_report(sonar: ToolOutcome, semgrep: ToolOutcome) -> ScanReport:
    """Normalize + merge both outcomes into the persistable report."""
    sonar_flat = [issue for group in (sonar.value or {}).values() for issue in group]
    sonar_findings = normalize_sonar(sonar_flat, []) if sonar.value else []
    semgrep_findings = normalize_semgrep(semgrep.value) if semgrep.value else []
    merged = merge_findings(sonar_findings, semgrep_findings)

    tools_run = []
    tools_failed: list[ToolFailure] = []
    for name, outcome in (("sonarqube", sonar), ("semgrep", semgrep)):
        if outcome.failed:
            tools_failed.append(ToolFailure(tool=name, error=outcome.error or ""))
        elif outcome.value is not None:
            tools_run.append(name)

    return ScanReport(
        scan_id=uuid.uuid4().hex,
        tools_run=tools_run,
        tools_failed=tools_failed,
        findings=merged,
    )


async def run_static_analysis(
    *,
    review_id,
    project_key: str,
    files: list[dict],
    language: str,
) -> StaticAnalysisResult:
    """Run SonarQube and Semgrep concurrently and merge their findings.

    ``files`` is the ``[{"filename", "content"}]`` workspace; an empty
    list means neither tool can run (precondition note for SonarQube,
    matching the pre-Semgrep behaviour).
    """
    if not files:
        sonar = ToolOutcome(None, "SonarQube scan skipped: no fetchable file contents")
        semgrep = ToolOutcome()
    else:
        sonar, semgrep = await asyncio.gather(
            _run_sonar(project_key, files, language),
            _run_semgrep(files),
        )

    report = _build_report(sonar, semgrep)
    # Give every finding ±10 lines of real source (agents validate against
    # it; the persisted scan report serves it too).
    enrich_snippets(report.findings, files)

    if sonar.failed and semgrep.failed:
        logger.error(
            "Static analysis unavailable for review %s: sonarqube=%s; " "semgrep=%s",
            review_id,
            sonar.error,
            semgrep.error,
        )
    elif sonar.error or semgrep.error:
        logger.warning(
            "Partial static analysis for review %s: sonarqube=%s; "
            "semgrep=%s (findings from %s)",
            review_id,
            sonar.error,
            semgrep.error,
            report.tools_run or "no tool",
        )

    return StaticAnalysisResult(
        sonar_groups=sonar.value or _EMPTY_SONAR_GROUPS,
        report=report,
        sonar_error=sonar.error,
        semgrep_error=semgrep.error,
        both_failed=sonar.failed and semgrep.failed,
    )
