"""Dev-only local-review endpoint for the VS Code extension.

This endpoint exists for extension development. It has no user/org identity,
uses the global settings and the system LLM, never persists source, and never
calls GitHub. Production auth/org-scoped routes are a separate checkpoint.
"""

import asyncio
import hashlib
import logging
import secrets
import time
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.schemas.local_review import (
    LocalReviewFinding,
    LocalReviewRequest,
    LocalReviewResult,
    LocalReviewStatistics,
)
from app.services.agents import AgentComment
from app.services.llm_client import BaseLLMClient
from app.services.normalizers import NormalizedFinding
from app.services.org_settings import EffectiveSettings, resolve_org_settings
from app.services.review_engine import (
    build_context,
    cap_diff,
    resolve_review_llm,
    run_agent_stage,
    run_static_stage,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_CONTENT_TOO_LARGE_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)

_AGENT_SEVERITY = {
    "suggestion": "low",
    "info": "info",
    "warning": "medium",
    "error": "high",
}


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Not found",
    )


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    return host == "::1" or host == "localhost" or host.startswith("127.")


def _require_dev_access(request: Request) -> None:
    """Fail closed unless dev mode, loopback, and the dev token all match."""
    if not settings.LOCAL_REVIEW_DEV_MODE:
        raise _not_found()

    if request.headers.get("x-forwarded-for"):
        # Never trust a forwarded request on a dev-only unauthenticated path.
        raise _not_found()

    client_host = request.client.host if request.client else None
    if not _is_loopback(client_host):
        raise _not_found()

    supplied = request.headers.get("x-codesage-dev-token", "")
    expected = settings.LOCAL_REVIEW_DEV_TOKEN
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid development token",
        )


def _agent_severity(value: str) -> str:
    return _AGENT_SEVERITY.get(str(value or "").lower(), "info")


def _agent_id(comment: AgentComment) -> str:
    key = "\x1f".join(
        (
            comment.source_domain or "",
            comment.file_path or "",
            str(comment.line_number if comment.line_number is not None else ""),
            comment.body or "",
            comment.suggestion or "",
        )
    )
    digest = hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"agent:{comment.source_domain or 'unknown'}:{digest}"


def _static_finding(finding: NormalizedFinding) -> LocalReviewFinding:
    return LocalReviewFinding(
        id=finding.id,
        source="static",
        native_severity=finding.severity,
        severity=finding.severity,
        file_path=finding.file_path,
        line_start=finding.line_start,
        line_end=finding.line_end,
        message=finding.title or finding.message,
        body=finding.message,
        suggestion=finding.fix_suggestion,
        snippet=finding.snippet,
        tool=finding.tool,
        rule_id=finding.rule_id,
        category=finding.category,
        also_detected_by=list(finding.also_detected_by),
    )


def _agent_finding(comment: AgentComment) -> LocalReviewFinding:
    body = comment.body or ""
    first_line = body.splitlines()[0] if body else ""
    line = comment.line_number
    return LocalReviewFinding(
        id=_agent_id(comment),
        source="agent",
        native_severity=comment.severity,
        severity=_agent_severity(comment.severity),
        file_path=comment.file_path or "",
        line_start=line,
        line_end=line,
        message=first_line or body,
        body=body,
        suggestion=comment.suggestion,
        tool="agent",
        rule_id=comment.source_domain,
        category=comment.category,
        also_detected_by=[],
    )


def _degraded_reasons(
    analysis, agent_failures: list[str], truncated: bool
) -> list[str]:
    reasons: list[str] = []
    sonar_failed = analysis.sonar_error is not None
    semgrep_failed = analysis.semgrep_error is not None
    if sonar_failed and semgrep_failed:
        reasons.append("static_analysis_unavailable")
    else:
        if sonar_failed:
            reasons.append("sonarqube_failed")
        if semgrep_failed:
            reasons.append("semgrep_failed")
    reasons.extend(f"agent_failed:{name}" for name in agent_failures)
    if truncated:
        reasons.append("diff_truncated")
    return reasons


def _statistics(
    request: LocalReviewRequest, findings: list[LocalReviewFinding]
) -> LocalReviewStatistics:
    by_severity = Counter(finding.severity for finding in findings)
    by_category = Counter(finding.category or "general" for finding in findings)
    return LocalReviewStatistics(
        files_reviewed=len(request.snapshot.files),
        issues_found=len(findings),
        by_severity=dict(by_severity),
        by_category=dict(by_category),
    )


async def _run(
    request: LocalReviewRequest,
    db: AsyncSession,
) -> LocalReviewResult:
    started = time.perf_counter()

    effective: EffectiveSettings = await resolve_org_settings(db, None)
    sonar_files = [
        {"filename": file.path, "content": file.content}
        for file in request.files
        if file.status != "deleted"
    ]

    analysis = await run_static_stage(
        review_id=request.snapshot.id,
        project_key=f"{settings.SONARQUBE_PROJECT_PREFIX}-local-{request.snapshot.id[:8]}",
        files=sonar_files,
        language=request.language,
        effective=effective,
    )

    truncated = len(request.diff) > effective.diff_char_cap
    context = build_context(
        title=request.title,
        body=request.description,
        diff=cap_diff(request.diff, effective.diff_char_cap),
        language=request.language,
        analysis=analysis,
        effective=effective,
    )

    llm_client: BaseLLMClient = resolve_review_llm(None, effective)
    result = await run_agent_stage(context, llm_client)

    findings = [_static_finding(finding) for finding in analysis.report.findings]
    findings.extend(_agent_finding(comment) for comment in result.comments)
    agent_failures = list(getattr(result, "failed_agents", []))

    logger.info(
        "Local dev review completed",
        extra={
            "snapshot_id": request.snapshot.id,
            "files": len(request.files),
            "bytes": sum(len(file.content.encode("utf-8")) for file in request.files),
            "findings": len(findings),
            "degraded": _degraded_reasons(analysis, agent_failures, truncated),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        },
    )

    return LocalReviewResult(
        snapshot=request.snapshot,
        summary=result.summary,
        overall_severity=result.overall_severity,
        statistics=_statistics(request, findings),
        findings=findings,
        degraded_reasons=_degraded_reasons(analysis, agent_failures, truncated),
        agent_failures=agent_failures,
        diff_truncated=truncated,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


@router.post(
    "/local-reviews/dev",
    response_model=LocalReviewResult,
    dependencies=[Depends(_require_dev_access)],
    include_in_schema=settings.LOCAL_REVIEW_DEV_MODE,
    tags=["Local Reviews"],
)
async def create_dev_local_review(
    request: LocalReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LocalReviewResult:
    """Run a dev-only local review.

    Disabled unless ``LOCAL_REVIEW_DEV_MODE=true`` and a valid dev token is
    supplied from a loopback address. Never persists source or results.
    """
    if len(request.files) > settings.LOCAL_REVIEW_DEV_MAX_FILES:
        raise HTTPException(
            status_code=_CONTENT_TOO_LARGE_413,
            detail="Too many files",
        )
    total_bytes = sum(len(file.content.encode("utf-8")) for file in request.files)
    if total_bytes > settings.LOCAL_REVIEW_DEV_MAX_BYTES:
        raise HTTPException(
            status_code=_CONTENT_TOO_LARGE_413,
            detail="Source payload too large",
        )

    try:
        async with asyncio.timeout(settings.LOCAL_REVIEW_DEV_TIMEOUT_SECONDS):
            return await _run(request, db)
    except HTTPException:
        raise
    except TimeoutError:
        logger.warning(
            "Local dev review timed out", extra={"snapshot_id": request.snapshot.id}
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Local review timed out",
        ) from None
    except Exception:
        # The traceback stays server-side; never echo provider/tool bodies or
        # source content back to the extension.
        logger.exception(
            "Local dev review failed", extra={"snapshot_id": request.snapshot.id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Local review failed",
        ) from None
