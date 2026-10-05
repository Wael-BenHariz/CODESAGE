"""Coordinates parallel specialist agents for pull request reviews."""

import asyncio
import logging

from app.services.agents import (
    AgentResult,
    ComplexityAgent,
    OrchestratorAgent,
    PerformanceAgent,
    ReviewContext,
    ReviewResult,
    SecurityAgent,
    StyleAgent,
    TestCoverageAgent,
)
from app.services.llm_client import BaseLLMClient
from app.services.normalizers.schema import NormalizedFinding
from app.services.sonarqube import SonarIssue, _classify_issue

logger = logging.getLogger(__name__)

# The five specialist domains, in agent-declaration order below.
AGENT_DOMAINS = (
    "security",
    "complexity",
    "performance",
    "style",
    "test_coverage",
)


def domain_for_finding(finding: NormalizedFinding) -> str:
    """Route one unified finding to a specialist domain.

    Security categories come first — both analyzers' vulnerabilities and
    hotspots belong to the security agent regardless of payload shape.

    SonarQube findings then reconstruct their original ``SonarIssue`` from
    the raw payload (``normalize_sonar`` stores ``asdict(issue)``) and run
    it through ``_classify_issue`` — the exact classifier the pipeline
    used before findings were unified, so they land in the same agents as
    they always did.

    Semgrep has no such history: it routes by rule namespace — performance
    rules to the performance agent, everything else to style (the same
    catch-all the Sonar classifier uses for unclassified issues). Semgrep
    expresses no complexity or test-coverage findings.
    """
    if finding.category in ("vulnerability", "security_hotspot"):
        return "security"
    if finding.tool == "sonarqube":
        raw = finding.raw or {}
        if raw.get("type") in ("BUG", "VULNERABILITY", "CODE_SMELL"):
            return _classify_issue(
                SonarIssue(
                    key=str(raw.get("key", "")),
                    rule=str(raw.get("rule", "")),
                    severity=str(raw.get("severity", "INFO")),
                    type=str(raw.get("type", "")),
                    component=str(raw.get("component", "")),
                    line=raw.get("line"),
                    message=str(raw.get("message", "")),
                    effort=raw.get("effort"),
                    tags=list(raw.get("tags") or []),
                )
            )
    if ".performance." in finding.rule_id:
        return "performance"
    return "style"


class ReviewOrchestrator:
    """Run specialist agents in parallel, then synthesize their outputs."""

    def __init__(self, client: BaseLLMClient):
        self.client = client

    async def run(self, context: ReviewContext) -> ReviewResult:
        """Execute specialist agents concurrently and synthesize a final review.

        Each agent only ever sees its own domain's slice of the unified
        findings via ``context.with_findings(...)`` (routing by
        ``domain_for_finding``).

        ``context.enabled_agents`` (org setting, Step 4) filters which
        specialists run — ``None`` means all five; the orchestrator's
        summary call always runs. An explicit empty list leaves zero
        specialists, and ``synthesize`` falls back to its honest
        "no conclusions" body.
        """

        declared = [
            (SecurityAgent(self.client), "security"),
            (ComplexityAgent(self.client), "complexity"),
            (PerformanceAgent(self.client), "performance"),
            (StyleAgent(self.client), "style"),
            (TestCoverageAgent(self.client), "test_coverage"),
        ]
        if context.enabled_agents is not None:
            enabled = set(context.enabled_agents)
            pairs = [(agent, domain) for agent, domain in declared if domain in enabled]
            skipped = [domain for _, domain in declared if domain not in enabled]
            if skipped:
                logger.info(
                    "Review specialists disabled by org settings",
                    extra={"skipped_domains": skipped},
                )
        else:
            pairs = declared

        # One LLM call in flight at a time: parallel calls burst past the
        # free-tier per-minute quota (429) and overload the model (503).
        # Agents still run via gather with fault tolerance — just staggered.
        semaphore = asyncio.Semaphore(1)

        async def _run_limited(agent, domain):
            async with semaphore:
                slice_ = [
                    finding
                    for finding in context.findings
                    if domain_for_finding(finding) == domain
                ]
                return await agent.run(context.with_findings(slice_))

        results = await asyncio.gather(
            *(_run_limited(agent, domain) for agent, domain in pairs),
            return_exceptions=True,
        )

        valid_results: list[AgentResult] = []
        failed_agents: list[str] = []
        for (agent, domain), result in zip(pairs, results):
            if isinstance(result, AgentResult):
                # Step 7b: stamp provenance so the worker can match each
                # comment back to THIS domain's findings (the LLM never
                # supplies source metadata — plan §1.2).
                for comment in result.comments:
                    comment.source_domain = domain
                logger.info(
                    "Review agent succeeded",
                    extra={
                        "agent": result.agent,
                        "confidence": result.confidence,
                        "comments_count": len(result.comments),
                    },
                )
                valid_results.append(result)
            else:
                failed_agents.append(agent.AGENT_NAME)
                logger.warning(
                    "Review agent failed",
                    extra={"agent": agent.AGENT_NAME},
                    exc_info=(
                        (type(result), result, result.__traceback__)
                        if isinstance(result, Exception)
                        else None
                    ),
                )

        logger.info(
            "Synthesizing review agent outputs",
            extra={
                "valid_agent_count": len(valid_results),
                "failed_agents": failed_agents,
            },
        )
        review = await OrchestratorAgent(self.client).synthesize(
            context,
            valid_results,
            failed_agents=failed_agents,
        )
        review.usage = self.client.total_usage()
        return review
