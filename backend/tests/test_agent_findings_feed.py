"""Step 6: unified findings feed the specialist agents.

- ``domain_for_finding`` routes unified findings to the same domains the
  Sonar classifier always used (sonar payloads reuse ``_classify_issue``)
  and Semgrep by category/rule namespace.
- Prompts present BOTH analyzers and the validate/prioritize/chunk
  contract, with enriched snippets for validation.
- The orchestrator hands each agent only its own domain slice, and the
  synthesis prompt is honest about failed analyzers.

The LLM is mocked (``FakeLLM`` records every prompt and returns canned
JSON) — no network.
"""

import json
import re

from app.services.agents import (
    AgentComment,
    AgentResult,
    OrchestratorAgent,
    ReviewContext,
    SecurityAgent,
    StyleAgent,
)
from app.services.agents.specialist_agents import (
    MAX_FINDINGS_PER_AGENT,
    format_findings,
)
from app.services.llm_client import BaseLLMClient
from app.services.normalizers.schema import NormalizedFinding
from app.services.review_orchestrator import ReviewOrchestrator, domain_for_finding

# --- finding builders ---------------------------------------------------------


def _sonar_finding(
    *,
    issue_type: str = "CODE_SMELL",
    rule: str = "java:S1181",
    tags: list[str] | None = None,
    category: str = "code_smell",
    file_path: str = "src/A.java",
    line: int | None = 10,
    severity: str = "medium",
    message: str = "sonar message",
    cwe: list[str] | None = None,
    also_detected_by: list[str] | None = None,
    snippet: str | None = None,
) -> NormalizedFinding:
    """A sonar-derived finding whose ``raw`` mirrors ``asdict(SonarIssue)``."""
    return NormalizedFinding(
        tool="sonarqube",  # type: ignore[arg-type]
        rule_id=rule,
        message=message,
        severity=severity,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
        file_path=file_path,
        line_start=line,
        cwe=cwe or [],
        also_detected_by=also_detected_by or [],
        snippet=snippet,
        raw={
            "key": f"{rule}:{line}",
            "rule": rule,
            "severity": "MAJOR",
            "type": issue_type,
            "component": file_path,
            "line": line,
            "message": message,
            "effort": "5min",
            "tags": tags or [],
        },
    )


def _semgrep_finding(
    *,
    rule_id: str = "python.style.import-order",
    category: str = "best_practice",
    file_path: str = "app.py",
    line: int | None = 5,
    severity: str = "medium",
    message: str = "semgrep message",
) -> NormalizedFinding:
    return NormalizedFinding(
        tool="semgrep",  # type: ignore[arg-type]
        rule_id=rule_id,
        message=message,
        severity=severity,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
        file_path=file_path,
        line_start=line,
    )


# --- domain routing -----------------------------------------------------------


def test_security_categories_route_to_security():
    assert (
        domain_for_finding(
            _sonar_finding(issue_type="VULNERABILITY", category="vulnerability")
        )
        == "security"
    )
    # Hotspot raw payloads are API-shaped (no "type" key) — the category
    # check must win before any raw reconstruction.
    hotspot = _sonar_finding(category="security_hotspot")
    hotspot.raw = {"id": "AX1", "rule": "javasec:S1", "message": "weak hash"}
    assert domain_for_finding(hotspot) == "security"
    assert (
        domain_for_finding(
            _semgrep_finding(category="vulnerability", rule_id="java.lang.sqli")
        )
        == "security"
    )
    assert (
        domain_for_finding(_semgrep_finding(category="security_hotspot")) == "security"
    )


def test_sonar_payloads_keep_their_historic_domains():
    # Same classifier as the pre-unification pipeline (_classify_issue).
    assert (
        domain_for_finding(
            _sonar_finding(issue_type="CODE_SMELL", tags=["brain-overload"])
        )
        == "complexity"
    )
    assert (
        domain_for_finding(
            _sonar_finding(issue_type="CODE_SMELL", tags=["performance"])
        )
        == "performance"
    )
    assert (
        domain_for_finding(_sonar_finding(issue_type="CODE_SMELL", tags=["tests"]))
        == "test_coverage"
    )
    # Security tag on any type -> security (step 1 of the classifier).
    assert domain_for_finding(_sonar_finding(tags=["sql"])) == "security"
    # Plain bug, no special tags -> style (the historic catch-all).
    assert (
        domain_for_finding(_sonar_finding(issue_type="BUG", category="bug")) == "style"
    )


def test_semgrep_rules_route_by_category_and_namespace():
    assert (
        domain_for_finding(
            _semgrep_finding(
                rule_id="python.performance.subprocess-popen-with-shell-true",
                category="code_smell",
            )
        )
        == "performance"
    )
    assert (
        domain_for_finding(_semgrep_finding(rule_id="python.style.import-order"))
        == "style"
    )
    # Correctness bugs have no specialist — style is the catch-all.
    assert (
        domain_for_finding(
            _semgrep_finding(
                rule_id="python.correctness.dict-modified-iteration",
                category="bug",
            )
        )
        == "style"
    )


# --- prompt shape -------------------------------------------------------------


def test_specialist_prompt_two_analyzers_and_contract():
    agent = SecurityAgent(FakeLLM())
    context = ReviewContext(
        pr_title="Add login endpoint",
        language="python",
        diff="",
        findings=[
            _sonar_finding(
                issue_type="VULNERABILITY",
                category="vulnerability",
                rule="python:S4502",
                cwe=["CWE-95"],
                also_detected_by=["semgrep"],
                snippet="8: x = 1\n10: eval(payload)",
            )
        ],
    )

    prompt = agent._build_prompt(context)

    assert "Two static analyzers — SonarQube and Semgrep" in prompt
    assert "1. VALIDATE" in prompt
    assert "2. PRIORITIZE" in prompt
    assert "3. CHUNK" in prompt
    assert "## Findings (security) — SonarQube + Semgrep" in prompt
    assert "Title: Add login endpoint" in prompt
    # Cross-tool agreement + CWE + enriched snippet are all visible.
    assert "[sonarqube; also detected by semgrep]" in prompt
    assert "CWE-95" in prompt
    assert "10: eval(payload)" in prompt
    # Output contract unchanged (schema still required at the end).
    assert '"agent": "security"' in prompt


def test_format_findings_empty_and_file_level():
    assert format_findings([]) == "No issues found in this category."

    file_level = NormalizedFinding(
        tool="semgrep",  # type: ignore[arg-type]
        rule_id="python.best-practice.x",
        message="",
        title="Missing docstring",
        file_path="app.py",
        line_start=None,
    )
    out = format_findings([file_level])
    assert "(file level)" in out
    assert "Missing docstring" in out  # empty message falls back to title


def test_format_findings_caps_prompt_budget_severity_first():
    """TPM cap: at most MAX_FINDINGS_PER_AGENT entries, lowest cut first."""

    findings = [
        _sonar_finding(
            rule=f"java:S{i}",
            severity="low",
            line=i,
            message=f"low issue {i}",
        )
        for i in range(18)
    ]
    # Criticals appended LAST — naive truncation would drop them.
    findings += [
        _sonar_finding(
            rule="java:CRITICAL-1",
            severity="critical",
            line=91,
            message="first critical",
        ),
        _sonar_finding(
            rule="java:CRITICAL-2",
            severity="critical",
            line=92,
            message="second critical",
        ),
    ]

    out = format_findings(findings)

    assert out.count("- [") == MAX_FINDINGS_PER_AGENT
    assert "java:CRITICAL-1" in out and "java:CRITICAL-2" in out
    assert "low issue 17" not in out  # lowest severities are the ones cut
    assert "5 lower-severity findings omitted" in out  # 20 rendered, 15 kept


def test_format_findings_compact_location_tools_still_visible():
    """Compact header: file:line instead of boilerplate, agreement kept."""

    out = format_findings(
        [
            _sonar_finding(
                file_path="src/A.java",
                line=42,
                severity="critical",
                cwe=["CWE-89"],
                also_detected_by=["semgrep"],
                message="SQL injection",
            )
        ]
    )
    assert "src/A.java:42" in out
    assert "[sonarqube; also detected by semgrep]" in out
    assert "CWE-89" in out
    assert "SQL injection" in out


# --- orchestrator wiring (mocked LLM) -----------------------------------------


class FakeLLM(BaseLLMClient):
    """Records prompts and answers with canned JSON per prompt kind."""

    def __init__(self):
        super().__init__(api_key="test-key", model="fake-model")
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return self.model

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        self.prompts.append(prompt)
        if "You are synthesizing a GitHub PR code review" in prompt:
            return json.dumps(
                {"summary": "Synthesized summary.", "overall_severity": "error"}
            )
        # Specialist: no findings -> honest empty answer.
        if "No issues found in this category." in prompt:
            return json.dumps({"confidence": 0.5, "comments": []})
        # Distinct comment per domain so the merge keeps all of them.
        domain = re.search(r"## Findings \(([^)]+)\)", prompt).group(1)
        line = {
            "security": 1,
            "complexity": 2,
            "performance": 3,
            "style and maintainability": 4,
            "test coverage": 5,
        }[domain]
        return json.dumps(
            {
                "confidence": 0.9,
                "comments": [
                    {
                        "file_path": f"{domain}.py",
                        "line_number": line,
                        "severity": "warning",
                        "category": "general",
                        "body": f"{domain} finding",
                    }
                ],
            }
        )


def _orchestration_context() -> ReviewContext:
    """One finding per domain — sonar (4 historic buckets) + semgrep style."""
    return ReviewContext(
        pr_title="Refactor parsing",
        language="python",
        diff="",
        findings=[
            _sonar_finding(
                issue_type="VULNERABILITY",
                category="vulnerability",
                rule="java:S2077",
                file_path="src/A.java",
                line=10,
                also_detected_by=["semgrep"],
                snippet="8: query(userInput)",
            ),
            _sonar_finding(
                rule="java:S1181",
                tags=["brain-overload"],
                file_path="src/A.java",
                line=30,
            ),
            _semgrep_finding(
                rule_id="python.performance.subprocess-shell-true",
                category="code_smell",
                file_path="app.py",
                line=7,
            ),
            _semgrep_finding(
                rule_id="python.style.import-order",
                category="best_practice",
                file_path="app.py",
                line=5,
            ),
        ],
    )


async def test_orchestrator_feeds_each_agent_only_its_domain_findings():
    fake = FakeLLM()
    result = await ReviewOrchestrator(fake).run(_orchestration_context())

    specialist_prompts = [p for p in fake.prompts if "## Findings (" in p]
    synthesis_prompts = [
        p for p in fake.prompts if "You are synthesizing a GitHub PR" in p
    ]
    # test_coverage has no findings in this context -> the LLM call is
    # skipped entirely (empty slice returns a confident empty result).
    assert len(specialist_prompts) == 4
    assert not any("## Findings (test coverage)" in p for p in fake.prompts)
    assert len(synthesis_prompts) == 1
    # The skipped agent is a SUCCESS with zero comments, not a failure —
    # synthesis must not report it among the failed specialists.
    assert "failed specialist agents" not in synthesis_prompts[0]

    by_domain = {
        re.search(r"## Findings \(([^)]+)\)", p).group(1): p for p in specialist_prompts
    }
    for prompt in specialist_prompts:
        assert "1. VALIDATE" in prompt and "3. CHUNK" in prompt

    security = by_domain["security"]
    assert "java:S2077" in security
    assert "also detected by semgrep" in security
    assert "java:S1181" not in security  # other agents' findings excluded
    assert "python.style" not in security

    complexity = by_domain["complexity"]
    assert "java:S1181" in complexity
    assert "java:S2077" not in complexity

    performance = by_domain["performance"]
    assert "python.performance.subprocess-shell-true" in performance

    style = by_domain["style and maintainability"]
    assert "python.style.import-order" in style
    assert "java:S2077" not in style

    assert "test coverage" not in by_domain  # empty slice: no prompt at all

    # Output contract unchanged: merged comments + summary + severity.
    assert result.summary == "Synthesized summary."
    assert result.overall_severity == "error"
    assert {c.file_path for c in result.comments} == {
        "security.py",
        "complexity.py",
        "performance.py",
        "style and maintainability.py",
    }  # test_coverage reported none
    assert isinstance(result.usage, dict)


async def test_empty_slice_returns_without_calling_the_llm():
    """Empty domain slice -> confident empty result, zero LLM calls."""

    fake = FakeLLM()
    result = await StyleAgent(fake).run(ReviewContext(pr_title="t", diff=""))

    assert result.agent == "style"
    assert result.confidence == 1.0
    assert result.comments == []
    assert fake.prompts == []  # no prompt was ever sent


async def test_synthesis_is_honest_about_failed_analyzers():
    fake = FakeLLM()
    agent = OrchestratorAgent(fake)
    # synthesize short-circuits without an LLM call when NO agent result
    # exists — one real result keeps us on the summary path being tested.
    one_result = [
        AgentResult(
            agent="security",
            confidence=0.9,
            comments=[
                AgentComment(
                    file_path="a.py",
                    line_number=1,
                    severity="warning",
                    category="general",
                    body="finding",
                )
            ],
        )
    ]

    await agent.synthesize(
        ReviewContext(
            pr_title="t", diff="", sonar_scan_failed=True, semgrep_scan_failed=True
        ),
        one_result,
    )
    both = fake.prompts[-1]
    assert "BOTH analyzers (SonarQube and Semgrep) failed" in both
    assert "Static analysis unavailable" in both

    await agent.synthesize(
        ReviewContext(pr_title="t", diff="", sonar_scan_failed=True), one_result
    )
    sonar_only = fake.prompts[-1]
    assert "SonarQube scan failed" in sonar_only
    assert "come from Semgrep only" in sonar_only

    await agent.synthesize(
        ReviewContext(pr_title="t", diff="", semgrep_scan_failed=True), one_result
    )
    semgrep_only = fake.prompts[-1]
    assert "Semgrep scan failed" in semgrep_only
    assert "come from SonarQube only" in semgrep_only

    await agent.synthesize(ReviewContext(pr_title="t", diff=""), one_result)
    healthy = fake.prompts[-1]
    assert "IMPORTANT —" not in healthy  # no failure, no static-analysis note
    assert "SonarQube and/or Semgrep" in healthy  # two-analyzer wording
