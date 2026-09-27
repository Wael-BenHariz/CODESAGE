"""Final synthesis agent: merge specialist outputs and write the review summary.

Groq's free tier caps a single request at ~8000 TPM, so the full specialist
JSON (8-12k+ tokens on verbose runs) can never be sent to the LLM for
re-merging — and LLMs are unreliable at deduplication and counting anyway.
The orchestrator therefore:

1. merges findings deterministically in Python (dedupe by file+line, keep
   the strongest severity, compute statistics exactly), and
2. asks the LLM only for the Markdown summary + overall severity, feeding it
   compact one-line headlines (~1-2k tokens) instead of the raw JSON.

The summary still comes from the LLM; comment bodies are preserved verbatim.
"""

import logging
from collections import Counter
from typing import Any

from app.config import settings
from app.services.agents.base_agent import BaseAgent
from app.services.agents.schemas import (
    AgentComment,
    AgentResult,
    ReviewContext,
    ReviewResult,
    ReviewStatistics,
)
from app.services.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"suggestion": 0, "info": 1, "warning": 2, "error": 3}


class OrchestratorAgent(BaseAgent):
    """Deduplicate specialist outputs and produce the final review contract."""

    AGENT_NAME = "orchestrator"
    TEMPERATURE = settings.AGENT_ORCHESTRATOR_TEMPERATURE
    MAX_TOKENS = settings.AGENT_ORCHESTRATOR_MAX_TOKENS

    def __init__(self, client: BaseLLMClient):
        super().__init__(client)

    async def synthesize(
        self,
        context: ReviewContext,
        agent_results: list[AgentResult],
        failed_agents: list[str] | None = None,
    ) -> ReviewResult:
        """Merge specialist findings and ask the LLM for the final summary.

        ``failed_agents`` names the specialists that crashed or returned
        unparseable output — their findings are missing and the summary must
        say so instead of implying the code is clean.
        """

        failed_agents = failed_agents or []

        # All specialists failed: don't ask the LLM (it would only see an
        # empty list and claim "no issues") — return a deterministic warning.
        if not agent_results:
            names = ", ".join(failed_agents) if failed_agents else "all"
            logger.warning(
                "All review agents failed; returning deterministic fallback review",
                extra={"failed_agents": failed_agents},
            )
            return ReviewResult(
                summary=(
                    "## \u26a0\ufe0f Automated review unavailable\n\n"
                    f"All specialist review agents failed to return results ({names}). "
                    "**No conclusions can be drawn about this pull request** — "
                    "the absence of findings does not mean the code is clean. "
                    "Please review manually or re-run the automated review."
                ),
                overall_severity="warning",
                comments=[],
                statistics={
                    "files_reviewed": 0,
                    "issues_found": 0,
                    "by_severity": {},
                    "by_category": {},
                },
                usage=self.client.total_usage(),
            )

        # Deterministic merge: exact stats, verbatim bodies, strongest
        # finding wins per file+line — all independent of the LLM.
        merged = self._merge_comments(agent_results)
        statistics = self._compute_statistics(merged)
        usage = self.client.total_usage()

        prompt = self._build_summary_prompt(
            context,
            merged,
            failed_agents,
            total_agents=len(agent_results) + len(failed_agents),
        )
        try:
            data = await self._call_llm(prompt)
            summary = (
                (data.get("summary") or "").strip() if isinstance(data, dict) else ""
            )
            severity = data.get("overall_severity") if isinstance(data, dict) else None
            if not summary:
                raise ValueError("summary call returned an empty summary")
            if severity not in ("info", "warning", "error"):
                severity = "warning"
            return ReviewResult(
                summary=summary,
                overall_severity=severity,
                comments=merged,
                statistics=statistics,
                usage=usage,
            )
        except Exception:
            # The merged findings are real regardless of the summary call:
            # ship them in an honest fallback body instead of discarding them.
            logger.warning(
                "Orchestrator summary call failed; "
                "returning merged findings with fallback summary",
                exc_info=True,
            )
            return ReviewResult(
                summary=self._fallback_summary(merged),
                overall_severity="warning",
                comments=merged,
                statistics=statistics,
                usage=usage,
            )

    @staticmethod
    def _merge_comments(
        agent_results: list[AgentResult],
    ) -> list[AgentComment]:
        """Dedupe specialist findings by (file, line); strongest severity wins.

        Two agents flagging the same line are reporting the same issue with
        different wordings — keep the most severe (ties: first reported).
        """

        merged: dict[tuple[str, int | None], AgentComment] = {}
        for result in agent_results:
            for comment in result.comments:
                key = (comment.file_path, comment.line_number)
                existing = merged.get(key)
                if existing is None or _SEVERITY_RANK.get(
                    comment.severity, 1
                ) > _SEVERITY_RANK.get(existing.severity, 1):
                    merged[key] = comment
        return sorted(
            merged.values(),
            key=lambda c: (
                c.file_path,
                c.line_number if c.line_number is not None else -1,
            ),
        )

    @staticmethod
    def _compute_statistics(merged: list[AgentComment]) -> ReviewStatistics:
        """Compute final statistics exactly (no LLM arithmetic)."""

        files = {c.file_path for c in merged if c.file_path}
        return ReviewStatistics(
            files_reviewed=len(files),
            issues_found=len(merged),
            by_severity=dict(Counter(c.severity for c in merged)),
            by_category=dict(Counter(c.category for c in merged)),
        )

    @staticmethod
    def _fallback_summary(comments: list[AgentComment]) -> str:
        """Honest GitHub body when the summary LLM call fails.

        Still delivers the real merged findings — never claims cleanliness.
        """

        header = (
            "## \u26a0\ufe0f Automated review summary unavailable\n\n"
            "The orchestrator could not generate the overall summary (LLM call "
            "failed). **This is a partial review** — the specialist findings "
            "are listed below without a cross-cutting assessment. Please "
            "review manually or re-run the automated review.\n\n"
            f"### Specialist findings ({len(comments)})\n\n"
        )
        if not comments:
            return (
                header + "- No findings were reported by the specialists — this does "
                "not prove the code is clean, given the failed summary call."
            )
        lines = []
        for c in comments:
            loc = (
                f"{c.file_path}:{c.line_number}"
                if c.line_number is not None
                else c.file_path
            )
            lines.append(f"- **{loc}** `{c.severity}/{c.category}` — {c.body}")
        return header + "\n".join(lines)

    def _build_prompt(self, context: ReviewContext) -> str:
        raise NotImplementedError("Use synthesize() for OrchestratorAgent")

    def _build_summary_prompt(
        self,
        context: ReviewContext,
        merged: list[AgentComment],
        failed_agents: list[str] | None = None,
        total_agents: int = 0,
    ) -> str:
        """Summary-only prompt: compact headlines, not the raw agent JSON.

        Kept well under Groq's ~8000-token TPM even when specialists are
        verbose (raw JSON synthesis requests measured 8-13k and were 413'd).
        """

        failed_agents = failed_agents or []
        headlines = (
            "\n".join(
                f"- {c.file_path}:"
                f"{c.line_number if c.line_number is not None else '?'} "
                f"[{c.severity}/{c.category}] {c.body[:240]}"
                for c in merged
            )
            or "- (no specialist findings reported)"
        )

        if failed_agents:
            failure_note = f"""
IMPORTANT — failed specialist agents: {", ".join(failed_agents)} ({len(failed_agents)} of {total_agents}). Their findings are MISSING from the list below. You MUST:
- State in the summary that {len(failed_agents)} of {total_agents} specialist agents failed and the results are partial.
- NEVER claim or imply that "no issues were found" or that the code is clean — you have only seen a subset of the review.
- Do not invent findings for the failed agents; only report what the successful agents actually found."""
        else:
            failure_note = ""

        if context.sonar_scan_failed:
            static_note = """
IMPORTANT — static analysis was unavailable for this review: the SonarQube scan could not run (the specialist agents received no findings to refine). You MUST open the summary with a clear note such as "⚠️ Static analysis unavailable" and state that the review could not include SonarQube findings, so the absence of issues does not mean the code is clean."""
        else:
            static_note = ""

        return f"""You are synthesizing a GitHub PR code review.
The findings below were detected by SonarQube (static analysis) and explained by specialist review agents; they have already been deduplicated and merged by the orchestrator (strongest severity kept per file+line, statistics computed exactly).
Your task: write the final review summary and choose the overall severity.
Write:
1. A concise executive summary (2-3 sentences)
2. Critical issues (BLOCKER/CRITICAL) first
3. Findings grouped by file where multiple issues share a file
4. A short "What to fix first" priority list at the end
Format entirely in GitHub Markdown — ## headers, bullet points, backticks. This is posted verbatim as a PR review comment.
{failure_note}{static_note}
Rules:
- Return ONLY valid JSON (no markdown fences, no text before or after): {{"summary": "...", "overall_severity": "info|warning|error"}}
- The summary field will be posted verbatim as a GitHub Pull Request review comment body.
- Do not invent findings beyond the list below. If the list reports no findings, say the specialists reported no issues (unless the failed-agents note above says otherwise).
- overall_severity must be info, warning, or error — use error if any finding below has severity error.

Pull request context:
- Title: {context.pr_title}
- Description: {context.pr_body or "No description provided."}
- Language: {context.language}

Merged specialist findings ({len(merged)}):
{headlines}"""

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
