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
from app.services.groq import GroqClient
from app.services.sonarqube import SonarIssue

logger = logging.getLogger(__name__)


class ReviewOrchestrator:
    """Run specialist agents in parallel, then synthesize their outputs."""

    def __init__(self, client: GroqClient):
        self.client = client

    async def run(
        self,
        context: ReviewContext,
        sonar_groups: dict[str, list[SonarIssue]],
    ) -> ReviewResult:
        """Execute specialist agents concurrently and synthesize a final review.

        ``sonar_groups`` holds the pre-grouped SonarQube findings (keys from
        ``sonarqube.group_issues_by_agent``); each agent only ever sees its
        own domain's slice via ``context.with_issues(...)``.
        """

        agents = [
            SecurityAgent(self.client),
            ComplexityAgent(self.client),
            PerformanceAgent(self.client),
            StyleAgent(self.client),
            TestCoverageAgent(self.client),
        ]
        agent_domains = [
            "security",
            "complexity",
            "performance",
            "style",
            "test_coverage",
        ]

        # One LLM call in flight at a time: parallel calls burst past the
        # free-tier per-minute quota (429) and overload the model (503).
        # Agents still run via gather with fault tolerance — just staggered.
        semaphore = asyncio.Semaphore(1)

        async def _run_limited(agent, domain):
            async with semaphore:
                return await agent.run(
                    context.with_issues(sonar_groups.get(domain, []))
                )

        results = await asyncio.gather(
            *(
                _run_limited(agent, domain)
                for agent, domain in zip(agents, agent_domains)
            ),
            return_exceptions=True,
        )

        valid_results: list[AgentResult] = []
        failed_agents: list[str] = []
        for agent, result in zip(agents, results):
            if isinstance(result, AgentResult):
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
