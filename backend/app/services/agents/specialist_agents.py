"""Specialist review agents — SonarQube finding refinement.

SonarQube is the analyzer: it found the issues. The specialist agents no
longer scan raw code for problems. Each agent receives its pre-grouped slice
of SonarQube findings (see ``sonarqube.group_issues_by_agent``) and must:
explain them, propose fixes, group root causes, and prioritize by severity —
concisely, because the output lands in a GitHub PR comment.
"""

from app.config import settings
from app.services.agents.base_agent import BaseAgent
from app.services.agents.schemas import ReviewContext
from app.services.sonarqube import SonarIssue

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


def format_sonar_issues(issues: list[SonarIssue]) -> str:
    """Render a domain's SonarQube findings as a compact Markdown block."""
    if not issues:
        return "No issues found in this category."
    lines = []
    for issue in issues:
        line_ref = f"line {issue.line}" if issue.line else "file level"
        lines.append(
            f"- [{issue.severity}] {issue.rule} at "
            f"{issue.component} ({line_ref})\n  {issue.message}"
        )
    return "\n".join(lines)


class _SonarSpecialistAgent(BaseAgent):
    """Shared prompt builder: refine one domain's SonarQube findings."""

    DOMAIN = "general"

    def _format_sonar_issues(self, issues: list[SonarIssue]) -> str:
        return format_sonar_issues(issues)

    def _build_prompt(self, context: ReviewContext) -> str:
        issues_block = self._format_sonar_issues(context.sonar_issues)
        return f"""You are a {self.DOMAIN} code review specialist.
SonarQube has already analyzed the code and found the following issues.
Your job is NOT to find new issues — your job is to:
1. Explain each issue clearly in plain language a developer can act on
2. Provide a concrete fix or example where helpful
3. Group related issues if they share a root cause
4. Prioritize by severity (BLOCKER and CRITICAL first)
5. Be concise — this will appear in a GitHub PR comment

## Pull Request
Title: {context.pr_title}
Language: {context.language}

## SonarQube Findings ({self.DOMAIN})
{issues_block}

If there are no findings, return an empty comments array.

{_specialist_schema(self.AGENT_NAME)}"""


class SecurityAgent(_SonarSpecialistAgent):
    AGENT_NAME = "security"
    DOMAIN = "security"
    TEMPERATURE = settings.AGENT_SECURITY_TEMPERATURE
    MAX_TOKENS = 4096


class ComplexityAgent(_SonarSpecialistAgent):
    AGENT_NAME = "complexity"
    DOMAIN = "complexity"
    TEMPERATURE = settings.AGENT_COMPLEXITY_TEMPERATURE
    MAX_TOKENS = 2048


class PerformanceAgent(_SonarSpecialistAgent):
    AGENT_NAME = "performance"
    DOMAIN = "performance"
    TEMPERATURE = settings.AGENT_PERFORMANCE_TEMPERATURE
    MAX_TOKENS = 2048


class StyleAgent(_SonarSpecialistAgent):
    AGENT_NAME = "style"
    DOMAIN = "style and maintainability"
    TEMPERATURE = settings.AGENT_STYLE_TEMPERATURE
    MAX_TOKENS = 2048


class TestCoverageAgent(_SonarSpecialistAgent):
    AGENT_NAME = "test_coverage"
    DOMAIN = "test coverage"
    TEMPERATURE = settings.AGENT_TEST_TEMPERATURE
    MAX_TOKENS = 2048
