"""Normalize SonarQube output into the unified finding schema.

Maps SonarQube's native severity (BLOCKER..INFO) and type (BUG,
VULNERABILITY, CODE_SMELL, SECURITY_HOTSPOT) onto the unified
``severity``/``category`` scales, reduces ``<projectKey>:<path>``
component references to repo-relative paths, and rates separate security
hotspots by their ``vulnerabilityProbability`` (HIGH/MEDIUM/LOW).

Pure functions — the existing SonarQube pipeline (``sonarqube.scan``) is
untouched and keeps feeding ``SonarIssue`` objects to the agents.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from typing import Any

from app.services.normalizers.schema import Category, NormalizedFinding, Severity
from app.services.sonarqube import SonarIssue

# SonarQube issue severity -> unified severity.
SEVERITY_MAP: dict[str, Severity] = {
    "BLOCKER": "critical",
    "CRITICAL": "high",
    "MAJOR": "medium",
    "MINOR": "low",
    "INFO": "info",
}

# SonarQube issue type -> unified category.
CATEGORY_MAP: dict[str, Category] = {
    "BUG": "bug",
    "VULNERABILITY": "vulnerability",
    "CODE_SMELL": "code_smell",
    "SECURITY_HOTSPOT": "security_hotspot",
}

# Hotspot vulnerabilityProbability -> unified severity (unrated -> medium).
HOTSPOT_PROBABILITY_MAP: dict[str, Severity] = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}

# Titles are a single truncated line (they headline the agent prompts).
TITLE_MAX_CHARS = 160

_CWE_RE = re.compile(r"CWE-?(\d+)", re.IGNORECASE)
_AXX_OWASP_RE = re.compile(r"A\d{2}:\d{4}-[\w\- ]+")


def strip_component_prefix(component: str) -> str:
    """Reduce ``<projectKey>:src/App.java`` to ``src/App.java``.

    Mirrors the stripping done in ``sonarqube.get_issues`` — applied again
    here so hotspots and raw payloads are handled identically. Components
    without a prefix (already relative paths) pass through unchanged.
    """
    if ":" in component:
        return component.split(":", 1)[1]
    return component


def _to_line(value: Any) -> int | None:
    """Coerce an API line value to a positive int, else None (file-level)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _title(message: str) -> str:
    """First line of the message, truncated — never empty."""
    stripped = message.strip()
    if not stripped:
        return ""
    return stripped.splitlines()[0][:TITLE_MAX_CHARS]


def _extract_cwe(tags: Iterable[str]) -> list[str]:
    """CWE ids from tags like ``external/cwe/cwe-89`` -> ``["CWE-89"]``."""
    found: list[str] = []
    for tag in tags:
        for match in _CWE_RE.finditer(tag):
            cwe = f"CWE-{match.group(1)}"
            if cwe not in found:
                found.append(cwe)
    return found


def _extract_owasp(tags: Iterable[str]) -> list[str]:
    """OWASP entries from tags (``owasp*`` markers or ``A03:2021-...`` ids)."""
    found: list[str] = []
    for tag in tags:
        stripped = tag.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("owasp"):
            entry = stripped
        else:
            match = _AXX_OWASP_RE.search(stripped)
            entry = match.group(0) if match else ""
        if entry and entry not in found:
            found.append(entry)
    return found


def _issue_finding(issue: SonarIssue) -> NormalizedFinding:
    """Map one SonarIssue onto the unified schema."""
    component = strip_component_prefix(issue.component)
    line = _to_line(issue.line)
    tags = [str(t) for t in issue.tags]
    message = str(issue.message)
    return NormalizedFinding(
        tool="sonarqube",
        rule_id=issue.rule,
        title=_title(message),
        message=message,
        severity=SEVERITY_MAP.get(issue.severity.upper(), "info"),
        category=CATEGORY_MAP.get(issue.type.upper(), "best_practice"),
        file_path=component,
        line_start=line,
        line_end=line,
        cwe=_extract_cwe(tags),
        owasp=_extract_owasp(tags),
        raw=asdict(issue),
    )


def _hotspot_finding(raw: dict[str, Any]) -> NormalizedFinding:
    """Map one raw ``/api/hotspots/search`` payload onto the unified schema."""
    component = strip_component_prefix(str(raw.get("component") or ""))
    probability = str(raw.get("vulnerabilityProbability") or "").upper()
    line = _to_line(raw.get("line"))
    message = str(raw.get("message") or "Security hotspot detected")
    return NormalizedFinding(
        tool="sonarqube",
        rule_id=str(raw.get("rule") or ""),
        title=_title(message),
        message=message,
        severity=HOTSPOT_PROBABILITY_MAP.get(probability, "medium"),
        category="security_hotspot",
        file_path=component,
        line_start=line,
        line_end=line,
        raw=dict(raw),
    )


def normalize_sonar(
    issues: Sequence[SonarIssue],
    hotspots: Sequence[dict[str, Any]] = (),
) -> list[NormalizedFinding]:
    """Map SonarQube issues + raw hotspots onto ``NormalizedFinding``.

    ``issues`` are the ``SonarIssue`` objects produced by
    ``sonarqube.get_issues``; ``hotspots`` are raw ``/api/hotspots/search``
    payloads (they carry ``vulnerabilityProbability`` instead of a
    severity). Input order is preserved: issues first, then hotspots.
    """
    findings = [_issue_finding(issue) for issue in issues]
    findings.extend(_hotspot_finding(hotspot) for hotspot in hotspots)
    return findings
