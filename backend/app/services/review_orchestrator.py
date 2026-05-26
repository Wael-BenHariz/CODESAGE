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
from app.services.gemini import GeminiClient

logger = logging.getLogger(__name__)


class ReviewOrchestrator:
    """Run specialist agents in parallel, then synthesize their outputs."""

    def __init__(self, client: GeminiClient):
        self.client = client

    async def run(self, context: ReviewContext) -> ReviewResult:
        """Execute specialist agents concurrently and synthesize a final review."""

        agents = [
            SecurityAgent(self.client),
            ComplexityAgent(self.client),
            PerformanceAgent(self.client),
            StyleAgent(self.client),
            TestCoverageAgent(self.client),
        ]
        results = await asyncio.gather(
            *(agent.run(context) for agent in agents),
            return_exceptions=True,
        )

        valid_results: list[AgentResult] = []
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
                logger.warning(
                    "Review agent failed",
                    extra={"agent": agent.AGENT_NAME},
                    exc_info=(type(result), result, result.__traceback__)
                    if isinstance(result, Exception)
                    else None,
                )

        logger.info(
            "Synthesizing review agent outputs",
            extra={"valid_agent_count": len(valid_results)},
        )
        review = await OrchestratorAgent(self.client).synthesize(context, valid_results)
        review.usage = self.client.total_usage()
        return review
