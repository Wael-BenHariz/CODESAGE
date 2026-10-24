"""Reusable review stages shared by PR reviews and local (extension) reviews.

The PR worker owns GitHub fetching, database persistence, posting, and status
transitions. This module owns only the engine that can run without those
concerns:

    static analysis -> ReviewContext -> per-user/system LLM -> agents

Keeping the stages separate preserves the worker's ordering and transaction
semantics; callers decide whether to persist a scan report, post to GitHub, or
return the result to a local client.
"""

from app.services.agents import ReviewContext, ReviewResult
from app.services.llm_client import BaseLLMClient, resolve_llm_client
from app.services.org_settings import EffectiveSettings
from app.services.review_orchestrator import ReviewOrchestrator
from app.services.static_analysis import StaticAnalysisResult, run_static_analysis


def cap_diff(diff: str, cap: int) -> str:
    """Apply the org's effective diff cap with a visible truncation note."""
    if len(diff) <= cap:
        return diff
    return (
        diff[:cap] + "\n[diff truncated for LLM context limit — "
        "review the visible portion only]"
    )


def effective_model(user_model: str | None, org_model: str | None) -> str | None:
    """Model precedence: per-user -> org ``ai_model`` -> system default."""
    return user_model or org_model or None


def resolve_review_llm(
    llm_user,
    effective: EffectiveSettings,
) -> BaseLLMClient:
    """Resolve the LLM for one review, degrading to system Groq on bad config."""
    user_model = getattr(llm_user, "llm_model", None)
    return resolve_llm_client(
        provider=getattr(llm_user, "llm_provider", None),
        model=effective_model(user_model, effective.ai_model),
        api_key_encrypted=getattr(llm_user, "llm_api_key", None) if llm_user else None,
        base_url=getattr(llm_user, "llm_base_url", None) if llm_user else None,
    )


async def run_static_stage(
    *,
    review_id: str,
    project_key: str,
    files: list[dict],
    language: str,
    effective: EffectiveSettings,
) -> StaticAnalysisResult:
    """Run SonarQube + Semgrep with the org's effective enable flags."""
    return await run_static_analysis(
        review_id=review_id,
        project_key=project_key,
        files=files,
        language=language,
        sonar_enabled=effective.sonarqube_enabled,
        semgrep_enabled=effective.semgrep_enabled,
    )


def build_context(
    *,
    title: str,
    body: str | None,
    diff: str,
    language: str,
    analysis: StaticAnalysisResult,
    effective: EffectiveSettings,
) -> ReviewContext:
    """Build the specialist-agent context from the static-analysis result."""
    return ReviewContext(
        pr_title=title,
        pr_body=body,
        diff=diff,
        language=language,
        findings=analysis.report.findings,
        sonar_scan_failed=analysis.sonar_error is not None,
        semgrep_scan_failed=analysis.semgrep_error is not None,
        max_findings_per_agent=effective.max_findings_per_agent,
        enabled_agents=list(effective.enabled_agents),
    )


async def run_agent_stage(
    context: ReviewContext,
    client: BaseLLMClient,
) -> ReviewResult:
    """Run the five specialists and synthesize the final summary."""
    return await ReviewOrchestrator(client=client).run(context)
