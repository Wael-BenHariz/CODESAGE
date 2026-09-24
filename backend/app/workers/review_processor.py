"""
Review Processor
Worker that processes code review jobs using Gemini AI.
"""

import logging
import traceback
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Review, ReviewComment, PullRequest, Repository
from app.services.agents import ReviewContext
from app.services.groq import GroqClient
from app.services.github import github_service
from app.services.github_app import get_installation_token
from app.services.review_orchestrator import ReviewOrchestrator

logger = logging.getLogger(__name__)

# Hard cap on the unified diff sent to the LLM.
DIFF_MAX_CHARS = 100_000
DIFF_TRUNCATION_NOTE = "[diff truncated - showing first 100k characters]"
EMPTY_DIFF_SUMMARY = "No reviewable changes found."


class ReviewPostError(Exception):
    """GitHub PR review POST failure (carries HTTP status + raw response body)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"GitHub review POST failed ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


async def post_pr_review(
    full_name: str,
    pr_number: int,
    commit_sha: str,
    body: str,
    installation_token: str,
) -> int:
    """
    Post a single pull request review (summary body only, no inline comments).

    Args:
        full_name: Repository full name (owner/repo)
        pr_number: Pull request number
        commit_sha: HEAD sha to attach the review to (stored head_sha)
        body: Review summary markdown (posted verbatim)
        installation_token: GitHub App installation access token

    Returns:
        GitHub review ID

    Raises:
        ReviewPostError: On 401/403/404/422 responses (detail = raw body)
    """
    url = f"https://api.github.com/repos/{full_name}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"token {installation_token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Always COMMENT -- the bot must never approve or request changes.
    payload = {
        "commit_id": commit_sha,
        "body": body,
        "event": "COMMENT",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.status_code in (401, 403, 404, 422):
        raise ReviewPostError(response.status_code, response.text)
    response.raise_for_status()
    data = response.json()
    return int(data.get("id") or 0)


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


async def process_review_job(job_data: dict, db: AsyncSession) -> dict:
    """
    Process a code review job.

    Pipeline: load rows -> idempotency guard -> processing -> diff fetch
    (installation token, paginated, filtered, capped) -> LLM review ->
    post summary review to GitHub -> store results -> completed.

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
    result = await db.execute(
        select(Review).where(Review.id == review_id)
    )
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

        # Build capped diff content + detect primary language.
        diff_content = _build_diff_content(reviewable_files)
        if len(diff_content) > settings.LLM_DIFF_CHAR_CAP:
            diff_content = (
                diff_content[: settings.LLM_DIFF_CHAR_CAP]
                + "\n[diff truncated for LLM context limit — "
                "review the visible portion only]"
            )
        language = _detect_language(files)

        # Run specialist review agents in parallel, then synthesize.
        context = ReviewContext(
            pr_title=pr.title,
            pr_body=pr.body,
            diff=diff_content,
            language=language,
        )
        orchestrator = ReviewOrchestrator(client=GroqClient())
        review_result = (await orchestrator.run(context)).model_dump(exclude_none=True)
        summary = review_result.get("summary", "")

        # Post ONE summary review to GitHub (no inline comments), attached to
        # the head_sha stored by the webhook at event time.
        github_review_id = None
        post_note = None
        try:
            github_review_id = await post_pr_review(
                full_name=repo.full_name,
                pr_number=pr.number,
                commit_sha=pr.head_sha,
                body=summary,
                installation_token=token,
            )
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

        # Store results in DB.
        review.summary = summary
        review.overall_severity = review_result.get("overall_severity", "info")
        review.gemini_model = settings.GROQ_MODEL
        if review_result.get("usage"):
            review.tokens_used = review_result["usage"].get("total_tokens", 0)
        review.github_review_id = github_review_id
        if post_note:
            review.error_message = post_note
        review.completed_at = datetime.now(timezone.utc)
        review.status = "completed"

        comments = review_result.get("comments", [])
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
        }

    except Exception as e:
        error_message = _classify_error(e)
        logger.error("Review %s failed: %s\n%s", review_id, error_message, traceback.format_exc())
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
