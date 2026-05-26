"""Specialist review agents for parallel pull request analysis."""

from app.config import settings
from app.services.agents.base_agent import BaseAgent
from app.services.agents.schemas import ReviewContext


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


def _context_block(context: ReviewContext) -> str:
    pr_body = context.pr_body or "No description provided."
    return f"""## Pull Request Title
{context.pr_title}

## Pull Request Description
{pr_body}

## Programming Language
{context.language}

## Unified Diff
{context.diff}"""


class SecurityAgent(BaseAgent):
    AGENT_NAME = "security"
    TEMPERATURE = settings.AGENT_SECURITY_TEMPERATURE
    MAX_TOKENS = 4096

    def _build_prompt(self, context: ReviewContext) -> str:
        return f"""You are a security-focused code review agent.
Focus only on injection flaws, hardcoded secrets, insecure dependencies, auth and authorization issues, sensitive data exposure, unsafe deserialization, and insecure error handling.
Ignore style-only concerns unless they directly create security risk.

{_context_block(context)}

{_specialist_schema(self.AGENT_NAME)}"""


class ComplexityAgent(BaseAgent):
    AGENT_NAME = "complexity"
    TEMPERATURE = settings.AGENT_COMPLEXITY_TEMPERATURE
    MAX_TOKENS = 2048

    def _build_prompt(self, context: ReviewContext) -> str:
        return f"""You are a complexity-focused code review agent.
Focus only on cyclomatic/cognitive complexity, deep nesting, long functions, god classes, unclear branching logic, and maintainability risk caused by control flow.

{_context_block(context)}

{_specialist_schema(self.AGENT_NAME)}"""


class PerformanceAgent(BaseAgent):
    AGENT_NAME = "performance"
    TEMPERATURE = settings.AGENT_PERFORMANCE_TEMPERATURE
    MAX_TOKENS = 2048

    def _build_prompt(self, context: ReviewContext) -> str:
        return f"""You are a performance-focused code review agent.
Focus only on algorithmic inefficiency, memory leaks, redundant computation, missing caching, blocking I/O in async code, database query inefficiency, and avoidable latency.

{_context_block(context)}

{_specialist_schema(self.AGENT_NAME)}"""


class StyleAgent(BaseAgent):
    AGENT_NAME = "style"
    TEMPERATURE = settings.AGENT_STYLE_TEMPERATURE
    MAX_TOKENS = 2048

    def _build_prompt(self, context: ReviewContext) -> str:
        return f"""You are a readability and maintainability code review agent.
Focus only on naming, DRY violations, poor or missing docstrings, SOLID violations, readability, cohesion, and code organization.

{_context_block(context)}

{_specialist_schema(self.AGENT_NAME)}"""


class TestCoverageAgent(BaseAgent):
    AGENT_NAME = "test_coverage"
    TEMPERATURE = settings.AGENT_TEST_TEMPERATURE
    MAX_TOKENS = 2048

    def _build_prompt(self, context: ReviewContext) -> str:
        return f"""You are a test coverage code review agent.
Focus only on missing tests for new logic, untested edge cases, weak assertions, brittle tests, missing regression coverage, and test structure improvements.

{_context_block(context)}

{_specialist_schema(self.AGENT_NAME)}"""
