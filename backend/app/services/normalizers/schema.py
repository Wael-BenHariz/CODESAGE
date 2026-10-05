"""Unified finding models: one schema for every static analyzer.

Every normalized finding carries a stable ``id`` — the sha1 fingerprint of
``tool + rule_id + file_path + line_start + message`` — so the same defect
keeps the same identity across scans and across tools (dedup keys off it).
"""

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field

# Unified severity scale (lowest -> highest). Each tool's native levels are
# mapped onto it by its normalizer.
Severity = Literal["info", "low", "medium", "high", "critical"]

# Finding taxonomy: mirrors SonarQube's issue types plus Semgrep's
# security/correctness categories, with best_practice as the catch-all for
# pure style/lint findings.
Category = Literal[
    "bug",
    "vulnerability",
    "code_smell",
    "security_hotspot",
    "best_practice",
]

# Static analyzers that can produce findings (extended as tools are added).
Tool = Literal["sonarqube", "semgrep"]


def fingerprint(
    tool: str,
    rule_id: str,
    file_path: str,
    line_start: int | None,
    message: str,
) -> str:
    """Stable identity for a finding: sha1 over the identifying fields.

    Field separator is ``\\x1f`` (unit separator) so concatenated field
    values can never collide (e.g. rule ``ab`` + file ``c`` vs rule ``a``
    + file ``bc``).
    """
    key = "\x1f".join(
        (
            tool,
            rule_id,
            file_path,
            "" if line_start is None else str(line_start),
            message,
        )
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class NormalizedFinding(BaseModel):
    """A single finding from any static analyzer, in the project's vocabulary."""

    # Computed on construction when left empty (see model_post_init).
    id: str = ""
    tool: Tool
    rule_id: str = ""
    title: str = ""
    message: str
    severity: Severity = "info"
    category: Category = "best_practice"
    file_path: str = ""
    line_start: int | None = None
    line_end: int | None = None
    snippet: str | None = None
    cwe: list[str] = Field(default_factory=list)
    owasp: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    # Other tools that found the SAME defect (cross-tool dedup, merge.py).
    # ``tool`` stays the primary producer; this lists only the others.
    also_detected_by: list[str] = Field(default_factory=list)
    fix_suggestion: str | None = None
    # Original tool payload, kept verbatim for debugging.
    raw: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any, /) -> None:
        if not self.id:
            self.id = fingerprint(
                self.tool,
                self.rule_id,
                self.file_path,
                self.line_start,
                self.message,
            )


class ToolFailure(BaseModel):
    """A tool that did not deliver results for a scan, and why."""

    tool: str
    error: str


class ScanReport(BaseModel):
    """Result of one scan: which tools ran, which failed, merged findings."""

    scan_id: str
    tools_run: list[str] = Field(default_factory=list)
    tools_failed: list[ToolFailure] = Field(default_factory=list)
    findings: list[NormalizedFinding] = Field(default_factory=list)
    # Computed from findings when not supplied explicitly.
    summary: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any, /) -> None:
        if not self.summary:
            self.summary = self.build_summary(self.findings)

    @staticmethod
    def build_summary(findings: list[NormalizedFinding]) -> dict[str, Any]:
        """Counts by severity and by primary tool, plus the total."""
        by_severity: dict[str, int] = {}
        by_tool: dict[str, int] = {}
        for finding in findings:
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
            by_tool[finding.tool] = by_tool.get(finding.tool, 0) + 1
        return {
            "total": len(findings),
            "by_severity": by_severity,
            "by_tool": by_tool,
        }
