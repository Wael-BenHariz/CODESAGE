"""Schemas for multi-agent code review orchestration."""

from pydantic import BaseModel, Field

from app.services.normalizers.schema import NormalizedFinding


class ReviewContext(BaseModel):
    """Shared pull request context passed to every review agent."""

    pr_title: str
    pr_body: str | None = None
    diff: str
    language: str = "text"
    # Unified static-analysis findings (SonarQube + Semgrep, normalized and
    # cross-tool merged, snippets enriched) — the specialists' input. Each
    # agent only ever sees its domain slice via ``with_findings``; the diff
    # stays in the context for reference only.
    findings: list[NormalizedFinding] = Field(default_factory=list)
    # Which analyzers failed, so the summary can be honest (brief A7.3):
    # both => "static analysis unavailable", one => partial coverage note.
    sonar_scan_failed: bool = False
    semgrep_scan_failed: bool = False
    # Org-effective settings the pipeline passes down (Step 4): None means
    # "use the code default" so direct construction stays valid.
    max_findings_per_agent: int | None = None
    enabled_agents: list[str] | None = None

    def with_findings(self, findings: list[NormalizedFinding]) -> "ReviewContext":
        """Copy of this context carrying one agent's slice of findings."""
        return ReviewContext(
            pr_title=self.pr_title,
            pr_body=self.pr_body,
            diff=self.diff,
            language=self.language,
            findings=findings,
            sonar_scan_failed=self.sonar_scan_failed,
            semgrep_scan_failed=self.semgrep_scan_failed,
            max_findings_per_agent=self.max_findings_per_agent,
            enabled_agents=self.enabled_agents,
        )


class AgentComment(BaseModel):
    """Single specialist-agent finding."""

    file_path: str = ""
    line_number: int | None = None
    severity: str = "info"
    category: str = "general"
    body: str = ""
    suggestion: str | None = None
    # Provenance stamped by the orchestrator AFTER parsing (never read from
    # the LLM): which specialist domain produced this comment. Step 7b uses
    # it to scope the worker's match back to that domain's findings. None
    # only when a comment bypassed the orchestrator (tests, fallbacks).
    source_domain: str | None = None


class AgentResult(BaseModel):
    """Specialist-agent output contract."""

    agent: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    comments: list[AgentComment] = Field(default_factory=list)


class ReviewStatistics(BaseModel):
    """Statistics included in the final review result."""

    files_reviewed: int = 0
    issues_found: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)


class ReviewResult(BaseModel):
    """Final review result matching the existing GeminiService contract."""

    summary: str = ""
    overall_severity: str = "info"
    comments: list[AgentComment] = Field(default_factory=list)
    statistics: ReviewStatistics = Field(default_factory=ReviewStatistics)
    usage: dict[str, int] | None = None
