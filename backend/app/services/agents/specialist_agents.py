"""Specialist review agents — refinement of unified analyzer findings.

Two static analyzers (SonarQube and Semgrep) are the finders: they located
the issues, normalized them into the unified schema, and cross-tool
duplicates are already merged (``also_detected_by`` marks agreement). The
specialist agents receive their domain's slice of ``ReviewContext.findings``
(see ``review_orchestrator.domain_for_finding``) and must: validate each
finding against its ±10-line snippet, prioritize, chunk root causes, and
propose fixes — concisely, because the output lands in a GitHub PR comment.
"""

from app.config import settings
from app.services.agents.base_agent import BaseAgent
from app.services.agents.schemas import ReviewContext
from app.services.normalizers.schema import NormalizedFinding

SPECIALIST_SCHEMA = """Return ONLY valid JSON with this exact shape:
{
  "agent": "__AGENT_NAME__",
  "confidence": 0.0,
  "comments": [
    {
      "file_path": "path/to/file.py",
      "line_number": 42,
      "severity": "info|warning|error|suggestion",
      "category": "bug|security|performance|style|best_practice|general",
      "body": "Detailed finding",
      "suggestion": "Optional fix"
    }
  ]
}
Do not include markdown, code fences, prose, or keys outside this schema."""


def _specialist_schema(agent_name: str) -> str:
    return SPECIALIST_SCHEMA.replace("__AGENT_NAME__", agent_name)


def format_findings(findings: list[NormalizedFinding]) -> str:
    """Render a domain's unified findings as compact Markdown.

    Each entry: unified severity, producing tool(s) — including cross-tool
    agreement — rule id, file/line, CWE ids, the message, and the enriched
    ±10-line numbered snippet when one exists (that excerpt is what makes
    validation possible without re-scanning the code).
    """
    if not findings:
        return "No issues found in this category."
    blocks = []
    for finding in findings:
        line_ref = f"line {finding.line_start}" if finding.line_start else "file level"
        tools: str = finding.tool
        if finding.also_detected_by:
            tools += f"; also detected by {', '.join(finding.also_detected_by)}"
        header = (
            f"- [{finding.severity}] [{tools}] {finding.rule_id} at "
            f"{finding.file_path} ({line_ref})"
        )
        if finding.cwe:
            header += f" ({', '.join(finding.cwe)})"
        message = finding.message.strip() or finding.title
        entry = f"{header}\n  {message}"
        if finding.snippet:
            fenced = "\n".join(f"  {line}" for line in finding.snippet.splitlines())
            entry += f"\n  ```\n{fenced}\n  ```"
        blocks.append(entry)
    return "\n".join(blocks)


class _SpecialistAgent(BaseAgent):
    """Shared prompt builder: refine one domain's unified findings."""

    DOMAIN = "general"

    def _format_findings(self, findings: list[NormalizedFinding]) -> str:
        return format_findings(findings)

    def _build_prompt(self, context: ReviewContext) -> str:
        findings_block = self._format_findings(context.findings)
        return f"""You are a {self.DOMAIN} code review specialist.
Two static analyzers — SonarQube and Semgrep — analyzed this pull request; their findings for your domain are listed below. Each entry names the tool that found it, findings both tools agreed on are merged and marked "also detected by", and each finding carries a numbered ±10-line code excerpt.
Your job is NOT to re-scan the code from scratch. Your job is to:
1. VALIDATE — check each finding against its code excerpt and this change; drop false positives and findings irrelevant to the pull request
2. PRIORITIZE — order by unified severity and real-world impact (error first)
3. CHUNK — merge findings that share one root cause into a single comment instead of repeating per-line noise
4. Explain each kept finding plainly and propose a concrete fix
5. Be concise — this will appear in a GitHub PR comment

## Pull Request
Title: {context.pr_title}
Language: {context.language}

## Findings ({self.DOMAIN}) — SonarQube + Semgrep
{findings_block}

If there are no findings, return an empty comments array.

{_specialist_schema(self.AGENT_NAME)}"""


class SecurityAgent(_SpecialistAgent):
    AGENT_NAME = "security"
    DOMAIN = "security"
    TEMPERATURE = settings.AGENT_SECURITY_TEMPERATURE
    MAX_TOKENS = 4096


class ComplexityAgent(_SpecialistAgent):
    AGENT_NAME = "complexity"
    DOMAIN = "complexity"
    TEMPERATURE = settings.AGENT_COMPLEXITY_TEMPERATURE
    MAX_TOKENS = 2048


class PerformanceAgent(_SpecialistAgent):
    AGENT_NAME = "performance"
    DOMAIN = "performance"
    TEMPERATURE = settings.AGENT_PERFORMANCE_TEMPERATURE
    MAX_TOKENS = 2048


class StyleAgent(_SpecialistAgent):
    AGENT_NAME = "style"
    DOMAIN = "style and maintainability"
    TEMPERATURE = settings.AGENT_STYLE_TEMPERATURE
    MAX_TOKENS = 2048


class TestCoverageAgent(_SpecialistAgent):
    AGENT_NAME = "test_coverage"
    DOMAIN = "test coverage"
    TEMPERATURE = settings.AGENT_TEST_TEMPERATURE
    MAX_TOKENS = 2048
