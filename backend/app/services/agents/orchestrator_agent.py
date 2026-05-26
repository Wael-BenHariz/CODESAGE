"""Final synthesis agent for specialist review outputs."""

import json
from typing import Any

from app.config import settings
from app.services.agents.base_agent import BaseAgent
from app.services.agents.schemas import AgentResult, ReviewContext, ReviewResult
from app.services.gemini import GeminiClient


class OrchestratorAgent(BaseAgent):
    """Deduplicate specialist outputs and produce the final review contract."""

    AGENT_NAME = "orchestrator"
    TEMPERATURE = settings.AGENT_ORCHESTRATOR_TEMPERATURE
    MAX_TOKENS = settings.AGENT_ORCHESTRATOR_MAX_TOKENS

    def __init__(self, gemini_client: GeminiClient):
        super().__init__(gemini_client)

    async def synthesize(
        self,
        context: ReviewContext,
        agent_results: list[AgentResult],
    ) -> ReviewResult:
        """Call Gemini once to merge specialist findings into final review output."""

        prompt = self._build_synthesis_prompt(context, agent_results)
        raw = await self.gemini_client.generate(
            prompt,
            temperature=self.TEMPERATURE,
            max_tokens=self.MAX_TOKENS,
        )
        try:
            data = self._parse_response(raw)
            return ReviewResult.model_validate(data)
        except Exception:
            return ReviewResult(
                summary=raw[:500] if raw else "Failed to generate review",
                overall_severity="info",
                comments=[],
                statistics={
                    "files_reviewed": 0,
                    "issues_found": 0,
                    "by_severity": {},
                    "by_category": {},
                },
                usage=self.gemini_client.total_usage(),
            )

    def _build_prompt(self, context: ReviewContext) -> str:
        raise NotImplementedError("Use synthesize() for OrchestratorAgent")

    def _build_synthesis_prompt(
        self,
        context: ReviewContext,
        agent_results: list[AgentResult],
    ) -> str:
        payload = [result.model_dump(exclude_none=True) for result in agent_results]
        return f"""You are the final code review orchestrator.
You receive JSON outputs from specialist review agents. Deduplicate overlapping findings, resolve severity conflicts for the same file and line, merge comments into a single useful list, produce a concise summary, compute overall_severity, and compute final statistics.

Rules:
- Return ONLY valid JSON.
- Preserve the existing final review schema exactly.
- Do not include agent names or confidence at the top level.
- If multiple agents report the same file_path and line_number, keep the strongest, clearest finding.
- overall_severity must be one of: info, warning, error.
- Comment severity must be one of: info, warning, error, suggestion.
- Comment category must be one of: bug, security, performance, style, best_practice, general.

Pull request context:
- Title: {context.pr_title}
- Description: {context.pr_body or "No description provided."}
- Language: {context.language}

Specialist outputs:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Return this exact shape:
{{
  "summary": "Overall assessment of the changes (2-4 sentences)",
  "overall_severity": "info|warning|error",
  "comments": [
    {{
      "file_path": "path/to/file.py",
      "line_number": 42,
      "severity": "info|warning|error|suggestion",
      "category": "bug|security|performance|style|best_practice|general",
      "body": "Detailed comment about the issue",
      "suggestion": "Optional code suggestion if applicable"
    }}
  ],
  "statistics": {{
    "files_reviewed": 5,
    "issues_found": 8,
    "by_severity": {{"error": 1, "warning": 3, "info": 4}},
    "by_category": {{"bug": 2, "security": 1, "style": 3, "performance": 2}}
  }}
}}"""

    def _parse_response(self, raw: str) -> dict[str, Any]:
        data = super()._parse_response(raw)
        data.setdefault("summary", "")
        data.setdefault("overall_severity", "info")
        data.setdefault("comments", [])
        data.setdefault(
            "statistics",
            {
                "files_reviewed": 0,
                "issues_found": 0,
                "by_severity": {},
                "by_category": {},
            },
        )
        return data
