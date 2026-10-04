"""
Review Processor
Worker that processes code review jobs using Gemini AI.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Org, PullRequest, Repository, Review, ReviewComment, User
from app.redis import get_redis
from app.services.agents import ReviewContext
from app.services.github import github_service
from app.services.github_app import fetch_file_content, get_installation_token
from app.services.llm_client import resolve_llm_client
from app.services.org_settings import resolve_org_settings
from app.services.review_orchestrator import ReviewOrchestrator
from app.services.review_posting import ReviewPostError, post_review_to_github
from app.services.scan_report_store import persist_scan_report
from app.services.static_analysis import run_static_analysis

logger = logging.getLogger(__name__)

# Hard cap on the unified diff sent to the LLM.
DIFF_MAX_CHARS = 100_000
DIFF_TRUNCATION_NOTE = "[diff truncated - showing first 100k characters]"
EMPTY_DIFF_SUMMARY = "No reviewable changes found."

# Per-org review-slot semaphore (Step 4): INCR/DECR counter with a TTL so
# a crashed worker cannot leak slots. Availability over strict enforcement
# — a semaphore problem never fails a review (structured warning instead).
ORG_SLOT_KEY = "codesage:org:{org_id}:active_reviews"
ORG_SLOT_TTL_SECONDS = 600
ORG_SLOT_POLL_SECONDS = 2.0
ORG_SLOT_MAX_WAIT_SECONDS = 120.0

# Comment severity -> scan vocabulary for the ``min_severity_to_post``
# gate (Step 4): specialist comments speak error/warning/suggestion/info,
# org settings speak info/low/medium/high/critical. Unknown values map to
# the floor ("info") — never silently dropped from consideration.
_COMMENT_SEVERITY_MAP = {
    "info": "info",
    "suggestion": "low",
    "warning": "medium",
    "error": "high",
}
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _classify_error(exc: Exception) -> str:
    """Map an exception to a review.error_message string."""
    if isinstance(exc, ReviewPostError):
        if exc.status_code in (401, 403):
            return f"installation token error: GitHub review POST returned {exc.status_code}"
        if exc.status_code == 422:
            return f"GitHub review POST rejected (422): {exc.detail}"
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        url = str(exc.request.url) if exc.request is not None else ""
        status_code = exc.response.status_code if exc.response is not None else None
        if "api.groq.com" in url:
            return f"Groq API error: HTTP {status_code} for {url.split('?')[0]}"
        if status_code in (401, 403):
            return f"installation token error: GitHub API returned {status_code}"
        if status_code == 404:
            return "GitHub API 404: repository or pull request was deleted"
        return f"GitHub API error: {exc}"
    if isinstance(exc, httpx.TimeoutException):
        return f"Timeout calling GitHub or Groq API: {exc}"
    return str(exc)


async def _resolve_org_id(db: AsyncSession, installation_id: int) -> UUID | None:
    """Org for this review: chain join ``installation -> orgs`` (Q1).

    ``None`` when no org row is linked to the installation (e.g. 013
    seeding had nothing to seed) — the worker then runs on global
    defaults and skips the per-org slot limit.
    """
    return await db.scalar(select(Org.id).where(Org.installation_id == installation_id))


def _cap_diff(diff: str, cap: int) -> str:
    """Apply the effective ``diff_char_cap`` with the LLM-context note."""
    if len(diff) <= cap:
        return diff
    return (
        diff[:cap] + "\n[diff truncated for LLM context limit — "
        "review the visible portion only]"
    )


def _effective_model(user_model: str | None, org_model: str | None) -> str | None:
    """Model-name precedence (Step 4): per-user -> org ``ai_model`` -> None.

    ``None`` lets ``resolve_llm_client`` fall back to the system default;
    the provider choice is never touched here.
    """
    return user_model or org_model or None


def _meets_min_severity(comments: list[dict], threshold: str) -> bool:
    """Does any posted finding reach ``min_severity_to_post``?

    ``threshold="info"`` (the default) always passes — the floor means
    "post everything", which keeps the auto path byte-identical to the
    pre-org-settings behaviour even for a review with zero comments.
    """
    if threshold not in _SEVERITY_RANK or threshold == "info":
        return True
    floor = _SEVERITY_RANK[threshold]
    for comment in comments:
        mapped = _COMMENT_SEVERITY_MAP.get(str(comment.get("severity", "info")), "info")
        if _SEVERITY_RANK[mapped] >= floor:
            return True
    return False


async def _acquire_org_slot(
    org_id: UUID,
    limit: int,
    *,
    poll_seconds: float = ORG_SLOT_POLL_SECONDS,
    max_wait_seconds: float = ORG_SLOT_MAX_WAIT_SECONDS,
    client=None,
) -> bool:
    """Take one of the org's review slots; ``True`` = slot held.

    INCR then check: over ``limit`` -> DECR (release the attempt) and
    poll until ``max_wait_seconds``. Timeout, Redis error, or a nonsense
    limit -> ``False`` with a structured warning: the caller proceeds
    anyway (availability over strict enforcement).
    """
    client = client if client is not None else get_redis()
    key = ORG_SLOT_KEY.format(org_id=org_id)
    limit = max(1, int(limit))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait_seconds
    while True:
        try:
            count = int(await client.incr(key))
            await client.expire(key, ORG_SLOT_TTL_SECONDS)
            if count <= limit:
                return True
            await client.decr(key)  # refusal: give the attempt back
        except Exception:
            logger.warning(
                "Review slot semaphore unavailable for org %s — proceeding "
                "without a slot",
                org_id,
                exc_info=True,
                extra={"org_id": str(org_id), "limit": limit},
            )
            return False
        if loop.time() >= deadline:
            logger.warning(
                "Timed out waiting for a review slot for org %s — proceeding " "anyway",
                org_id,
                extra={
                    "org_id": str(org_id),
                    "limit": limit,
                    "waited_seconds": max_wait_seconds,
                },
            )
            return False
        await asyncio.sleep(poll_seconds)


async def _release_org_slot(org_id: UUID, *, client=None) -> None:
    """Give the slot back (``finally`` path); never raises."""
    client = client if client is not None else get_redis()
    key = ORG_SLOT_KEY.format(org_id=org_id)
    try:
        remaining = int(await client.decr(key))
        if remaining <= 0:
            await client.delete(key)
    except Exception:
        logger.warning(
            "Failed to release review slot for org %s",
            org_id,
            exc_info=True,
            extra={"org_id": str(org_id)},
        )


async def process_review_job(job_data: dict, db: AsyncSession) -> dict:
    """
    Process a code review job.

    Pipeline: load rows -> idempotency guard -> processing -> org settings
    (``resolve_org_settings``) -> trigger gate -> per-org slot -> diff
    fetch (installation token, paginated, filtered, capped) -> full file
    contents fetched for the analyzers -> SonarQube + Semgrep static
    analysis IN PARALLEL (normalized, merged, persisted as a scan_report)
    -> grouped SonarQube issues refine the specialist agents -> synthesis
    -> post summary review to GitHub (auto mode, subject to
    ``min_severity_to_post``; staged mode parks it as ``ready_to_post``)
    -> store results -> completed.

    Static analysis failures never fail the review: each tool is
    fault-isolated (note + ``tools_failed`` entry), the scan report is
    persisted best-effort, and both tools failing only empties the
    findings while the review still completes.

    Args:
        job_data: Job payload with review_id
        db: Database session

    Returns:
        Processing result
    """
    review_id = job_data.get("review_id")

    if not review_id:
        return {"success": False, "error": "Missing review_id"}

    # Get review record
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()

    if not review:
        return {"success": False, "error": "Review not found"}

    # Idempotency guard: only pending reviews are processed.
    if review.status != "pending":
        logger.warning(
            "Skipping review %s: status is %r (not pending)", review_id, review.status
        )
        return {
            "success": True,
            "review_id": review_id,
            "skipped": "review not pending",
        }

    # Update status to processing
    review.status = "processing"
    await db.commit()

    org_id: UUID | None = None
    slot_held = False
    try:
        # Load PullRequest -> Repository -> GitHubInstallation
        pr_result = await db.execute(
            select(PullRequest).where(PullRequest.id == review.pull_request_id)
        )
        pr = pr_result.scalar_one_or_none()

        if not pr:
            raise ValueError("Pull request not found")

        repo_result = await db.execute(
            select(Repository)
            .options(selectinload(Repository.installation))
            .where(Repository.id == pr.repository_id)
        )
        repo = repo_result.scalar_one_or_none()

        if not repo or not repo.installation:
            raise ValueError("Repository or GitHub App installation not found")

        installation = repo.installation

        # Effective org settings (Step 4): resolve the org behind this
        # installation, then the single merge point. No org row -> global
        # defaults; a settings-resolution failure bubbles up as a review
        # failure (same as any other DB read in this job).
        org_id = await _resolve_org_id(db, installation.installation_id)
        effective = await resolve_org_settings(db, org_id)
        # Staged-posting column mirrors the org's effective setting from
        # here on: every terminal path (trigger gate, empty diff, staged,
        # auto, failure) commits this truthful value (Step 6).
        review.posting_mode = effective.posting_mode
        logger.info(
            "Review %s effective org settings",
            review_id,
            extra={
                "org_id": str(org_id) if org_id else None,
                "diff_char_cap": effective.diff_char_cap,
                "max_findings_per_agent": effective.max_findings_per_agent,
                "max_concurrent_reviews": effective.max_concurrent_reviews,
                "enabled_agents": effective.enabled_agents,
                "sonarqube_enabled": effective.sonarqube_enabled,
                "semgrep_enabled": effective.semgrep_enabled,
                "review_triggers": effective.review_triggers,
                "min_severity_to_post": effective.min_severity_to_post,
                "posting_mode": effective.posting_mode,
                "ai_model": effective.ai_model,
            },
        )

        # Trigger gate: the org disabled this trigger -> complete with a
        # note (never "failed": the org said so, the pipeline did not
        # break). Payload without a trigger key means "pull_request", so
        # in-flight jobs queued before Step 4 stay compatible.
        trigger = str(job_data.get("trigger") or "pull_request")
        if trigger not in effective.review_triggers:
            review.status = "completed"
            review.error_message = (
                f"Review skipped: trigger '{trigger}' disabled for this " "organization"
            )
            review.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "Review %s skipped: trigger %r disabled for org %s",
                review_id,
                trigger,
                org_id,
            )
            return {
                "success": True,
                "review_id": review_id,
                "skipped": "trigger disabled",
            }

        # Per-org concurrency slot (Step 4). Bounded wait, then proceed
        # anyway with a warning; released in the finally block below.
        if org_id is not None:
            slot_held = await _acquire_org_slot(
                org_id, effective.max_concurrent_reviews
            )

        # Installation access token (GitHub App JWT flow -- never the user
        # OAuth token, which may be expired or missing for App-installed repos).
        token = await get_installation_token(installation.installation_id)

        # Fetch changed files (paginated) using the installation token.
        owner, repo_name = repo.full_name.split("/", 1)
        files = await github_service.get_pull_request_files(
            owner,
            repo_name,
            pr.number,
            installation.installation_id,
        )

        # Filter out binary files / removed files that have no patch. If
        # nothing reviewable remains, finish cleanly without calling the LLM.
        reviewable_files = [f for f in files if f.get("patch")]
        if not reviewable_files:
            review.summary = EMPTY_DIFF_SUMMARY
            review.status = "completed"
            review.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return {
                "success": True,
                "review_id": review_id,
                "comments_count": 0,
                "summary": review.summary,
            }

        # Build capped diff content + detect primary language. The cap is
        # the org's effective ``diff_char_cap`` (clamped to DIFF_MAX_CHARS
        # by the merge point), replacing the direct config read.
        diff_content = _cap_diff(
            _build_diff_content(reviewable_files), effective.diff_char_cap
        )
        language = _detect_language(files)

        # SonarQube needs COMPLETE file contents, not just diff patches.
        sonar_files: list[dict] = []
        for f in reviewable_files:
            try:
                content = await fetch_file_content(
                    full_name=repo.full_name,
                    file_path=f["filename"],
                    ref=pr.head_sha,
                    token=token,
                )
            except Exception:
                # Enrichment only: one bad fetch must not kill the review.
                logger.warning(
                    "Failed to fetch content of %s for review %s",
                    f["filename"],
                    review_id,
                    exc_info=True,
                )
                continue
            if content:
                sonar_files.append({"filename": f["filename"], "content": content})

        # Unique throwaway project key per review (Community Edition allows
        # one branch per project — the project is always deleted after).
        project_key = f"{settings.SONARQUBE_PROJECT_PREFIX}-{str(review.id)[:8]}"

        # Static analysis: SonarQube + Semgrep run CONCURRENTLY over the
        # same file workspace. Each tool is fault-isolated — a failure is
        # recorded as a note + tools_failed entry, never as a review
        # failure; the review only loses static analysis when BOTH fail
        # (brief A7.3: "SonarQube failure => empty groups" generalized).
        # Org scanner flags (Step 4) skip a tool entirely: disabled !=
        # broken, so a skipped tool is neither run nor failed.
        analysis = await run_static_analysis(
            review_id=review_id,
            project_key=project_key,
            files=sonar_files,
            language=language,
            sonar_enabled=effective.sonarqube_enabled,
            semgrep_enabled=effective.semgrep_enabled,
        )
        sonar_error = analysis.sonar_error
        semgrep_error = analysis.semgrep_error

        # Persist the unified scan report best-effort: a report insert
        # failure must never fail a review — log it, roll back the
        # partial insert, and continue the pipeline.
        try:
            await persist_scan_report(db, review.id, analysis.report)
        except Exception:
            logger.warning(
                "Failed to persist scan report for review %s",
                review_id,
                exc_info=True,
            )
            await db.rollback()

        # Build context and run agents (diff still passed for context).
        # The specialist seams take the org's effective values: findings
        # per agent and the enabled-agent list (orchestrator summary
        # always runs).
        context = ReviewContext(
            pr_title=pr.title,
            pr_body=pr.body,
            diff=diff_content,
            language=language,
            findings=analysis.report.findings,
            sonar_scan_failed=sonar_error is not None,
            semgrep_scan_failed=semgrep_error is not None,
            max_findings_per_agent=effective.max_findings_per_agent,
            enabled_agents=list(effective.enabled_agents),
        )

        # Resolve the LLM client for the user who owns this installation:
        # per-user provider/model/key when configured, system Groq otherwise
        # (resolve_llm_client never raises — bad config degrades to default).
        # Model precedence (Step 4): per-user model -> org ai_model ->
        # system default; the provider choice is never overridden by the org.
        owner_result = await db.execute(
            select(User)
            .where(User.github_installation_id == installation.installation_id)
            .order_by(User.created_at.asc())
        )
        llm_user = owner_result.scalars().first()

        user_model = llm_user.llm_model if llm_user else None
        model = _effective_model(user_model, effective.ai_model)
        llm_client = resolve_llm_client(
            provider=llm_user.llm_provider if llm_user else None,
            model=model,
            api_key_encrypted=llm_user.llm_api_key if llm_user else None,
            base_url=llm_user.llm_base_url if llm_user else None,
        )
        logger.info(
            "Review %s using LLM provider=%s model=%s (user-configured=%s, "
            "org-model=%s)",
            review_id,
            type(llm_client).__name__,
            llm_client.model_name,
            bool(llm_user and llm_user.llm_provider),
            bool(effective.ai_model and not user_model),
        )

        orchestrator = ReviewOrchestrator(client=llm_client)
        review_result = (await orchestrator.run(context)).model_dump(exclude_none=True)
        summary = review_result.get("summary", "")
        comments = review_result.get("comments", [])

        # Persistable results BEFORE posting: the shared poster reads
        # review.summary / review.posting_mode off the row (Step 6).
        review.summary = summary
        review.overall_severity = review_result.get("overall_severity", "info")
        review.gemini_model = llm_client.model_name
        if review_result.get("usage"):
            review.tokens_used = review_result["usage"].get("total_tokens", 0)

        # Post ONE summary review to GitHub (no inline comments), attached to
        # the head_sha stored by the webhook at event time — unless the org's
        # effective settings say otherwise (Step 4):
        #   * posting_mode="staged" -> never post here; the review waits for
        #     an explicit human post (status ready_to_post);
        #   * min_severity_to_post (auto mode only) -> skip the GitHub post
        #     when no posted finding reaches the threshold; the default
        #     "info" always posts, keeping this path byte-identical to the
        #     pre-org-settings behaviour.
        github_review_id = None
        post_note = None
        staged = effective.posting_mode == "staged"
        if staged:
            logger.info(
                "Review %s staged: not posted to GitHub (awaiting manual post)",
                review_id,
            )
        elif not _meets_min_severity(comments, effective.min_severity_to_post):
            post_note = (
                "no findings at or above min_severity_to_post="
                f"{effective.min_severity_to_post}; GitHub post skipped"
            )
            logger.info("Review %s post skipped: %s", review_id, post_note)
        else:
            try:
                github_review_id = await post_review_to_github(
                    db, review, pr=pr, repo=repo, installation_token=token
                )
                review.posted_at = datetime.now(timezone.utc)
            except ReviewPostError as exc:
                if exc.status_code == 404:
                    # PR closed/deleted after the event: finish gracefully.
                    logger.warning(
                        "PR %s #%s no longer available for review posting: %s",
                        repo.full_name,
                        pr.number,
                        exc.detail,
                    )
                    post_note = "PR no longer available for review posting"
                elif exc.status_code == 422:
                    # GitHub often returns useful detail -- log the full body.
                    logger.error(
                        "GitHub review POST 422 for %s #%s -- full response body: %s",
                        repo.full_name,
                        pr.number,
                        exc.detail,
                    )
                    raise
                else:
                    raise

        # Store results in DB (summary/severity/model/tokens assigned
        # before the post above; posting_mode/posted_at set along the way).
        review.github_review_id = github_review_id
        # SonarQube/Semgrep failures are recorded but never fail the
        # review: it still completes with status=completed (brief A7.3).
        completion_notes = [
            note for note in (sonar_error, semgrep_error, post_note) if note
        ]
        if completion_notes:
            review.error_message = "; ".join(completion_notes)
        review.completed_at = datetime.now(timezone.utc)
        # Staged orgs park the review for the explicit human post (Step 6
        # surfaces the status end-to-end); auto orgs complete as ever.
        review.status = "ready_to_post" if staged else "completed"

        for comment in comments:
            review_comment = ReviewComment(
                review_id=review.id,
                pull_request_id=pr.id,
                file_path=comment.get("file_path", ""),
                line_number=comment.get("line_number"),
                body=comment.get("body", ""),
                severity=comment.get("severity", "info"),
                category=comment.get("category", "general"),
                suggestion=comment.get("suggestion"),
            )
            db.add(review_comment)

        await db.commit()

        return {
            "success": True,
            "review_id": review_id,
            "comments_count": len(comments),
            "summary": review.summary,
            "github_review_id": github_review_id,
            "status": review.status,
        }

    except Exception as e:  # noqa: BLE001 — never re-raise to BullMQ
        error_message = _classify_error(e)
        logger.error(
            "Review %s failed: %s\n%s", review_id, error_message, traceback.format_exc()
        )
        # Update review as failed (never re-raise: BullMQ must not retry
        # automatically; the DB row is the source of truth).
        review.status = "failed"
        review.error_message = error_message
        review.completed_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "success": False,
            "review_id": review_id,
            "error": error_message,
            "traceback": traceback.format_exc(),
        }

    finally:
        # Per-org slot release (Step 4): success, failure, and early
        # returns all pass through here; _release_org_slot never raises.
        if slot_held and org_id is not None:
            await _release_org_slot(org_id)


def _build_diff_content(files: list[dict]) -> str:
    """
    Build unified diff content from the patch fields of each file.

    Total size is capped at DIFF_MAX_CHARS with a truncation note appended.
    """
    diff_lines = []

    for file in files:
        filename = file.get("filename", "")
        status = file.get("status", "modified")
        additions = file.get("additions", 0)
        deletions = file.get("deletions", 0)

        diff_lines.append(f"\n{'='*80}")
        diff_lines.append(f"File: {filename} ({status}) +{additions} -{deletions}")
        diff_lines.append(f"{'='*80}\n")

        patch = file.get("patch", "")
        if patch:
            diff_lines.append(patch)

    diff = "\n".join(diff_lines)
    if len(diff) > DIFF_MAX_CHARS:
        diff = diff[:DIFF_MAX_CHARS] + "\n" + DIFF_TRUNCATION_NOTE
    return diff


def _detect_language(files: list[dict]) -> str:
    """
    Detect primary programming language by file-extension frequency.

    The extension with the most changed files wins. Falls back to
    "unknown" when no recognizable extension is present.
    """

    extensions: dict[str, str] = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".cs": "csharp",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".vue": "vue",
        ".svelte": "svelte",
    }

    ext_counts: dict[str, int] = {}

    for file in files:
        filename = file.get("filename", "")
        if "." not in filename:
            continue
        ext = "." + filename.rsplit(".", 1)[-1].lower()
        if ext in extensions:
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    if not ext_counts:
        return "unknown"

    top_ext = max(ext_counts, key=lambda e: ext_counts[e])
    return extensions[top_ext]
