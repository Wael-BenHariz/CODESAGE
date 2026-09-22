"""
Review Processor
Worker that processes code review jobs using Gemini AI.
"""

import traceback
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Review, ReviewComment, PullRequest, Repository
from app.services.agents import ReviewContext
from app.services.gemini import GeminiClient
from app.services.github import github_service
from app.services.review_orchestrator import ReviewOrchestrator


async def process_review_job(job_data: dict, db: AsyncSession) -> dict:
    """
    Process a code review job.
    
    Fetches PR details, calls Gemini API for review, and stores results.
    
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
    
    # Update status to processing
    review.status = "processing"
    await db.commit()
    
    try:
        # Get PR and repository info
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
        
        if not repo:
            raise ValueError("Repository not found")
        
        # Get changed files from GitHub
        owner, repo_name = repo.full_name.split("/", 1)
        files = await github_service.get_pull_request_files(
            owner,
            repo_name,
            pr.number,
            repo.installation.installation_id,
        )
        
        # Build diff content
        diff_content = await _build_diff_content(
            github_service,
            owner,
            repo_name,
            pr,
            files,
        )
        
        # Determine language from files
        language = _detect_language(files)
        
        # Run specialist review agents in parallel, then synthesize a final review.
        context = ReviewContext(
            pr_title=pr.title,
            pr_body=pr.body,
            diff=diff_content,
            language=language,
        )
        orchestrator = ReviewOrchestrator(client=GeminiClient())
        review_result = (await orchestrator.run(context)).model_dump(exclude_none=True)
        
        # Update review with results
        review.status = "completed"
        review.summary = review_result.get("summary", "")
        review.gemini_model = settings.GEMINI_MODEL
        
        # Store token usage
        if "usage" in review_result:
            review.tokens_used = review_result["usage"].get("total_tokens", 0)
        
        review.completed_at = datetime.now(timezone.utc)
        await db.commit()
        
        # Store review comments
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
            )
            db.add(review_comment)
        
        await db.commit()
        
        # Optionally post comments to GitHub
        await _post_comments_to_github(
            github_service,
            owner,
            repo_name,
            pr,
            repo.installation.installation_id,
            comments,
        )
        
        return {
            "success": True,
            "review_id": review_id,
            "comments_count": len(comments),
            "summary": review.summary,
        }
        
    except Exception as e:
        # Update review as failed
        review.status = "failed"
        review.error_message = str(e)
        review.completed_at = datetime.now(timezone.utc)
        await db.commit()
        
        return {
            "success": False,
            "review_id": review_id,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


async def _build_diff_content(
    github_service,
    owner: str,
    repo_name: str,
    pr,
    files: list[dict],
) -> str:
    """Build formatted diff content for review."""
    
    diff_lines = []
    
    for file in files[:50]:  # Limit to first 50 files
        filename = file.get("filename", "")
        status = file.get("status", "modified")
        additions = file.get("additions", 0)
        deletions = file.get("deletions", 0)
        
        diff_lines.append(f"\n{'='*80}")
        diff_lines.append(f"File: {filename} ({status}) +{additions} -{deletions}")
        diff_lines.append(f"{'='*80}\n")
        
        # Get patch if available
        patch = file.get("patch", "")
        if patch:
            diff_lines.append(patch)
        else:
            diff_lines.append(f"# Diff not available for {filename}")
    
    return "\n".join(diff_lines)


def _detect_language(files: list[dict]) -> str:
    """Detect primary programming language from file extensions."""
    
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
    
    language_counts: dict[str, int] = {}
    
    for file in files:
        filename = file.get("filename", "")
        ext = "." + filename.split(".")[-1] if "." in filename else ""
        
        lang = extensions.get(ext.lower(), "unknown")
        if lang != "unknown":
            language_counts[lang] = language_counts.get(lang, 0) + 1
    
    if language_counts:
        return max(language_counts, key=language_counts.get)
    
    return "text"


async def _post_comments_to_github(
    github_service,
    owner: str,
    repo_name: str,
    pr,
    installation_id: int,
    comments: list[dict],
) -> None:
    """
    Post review comments to GitHub.
    
    Groups comments by file and posts as a review.
    """
    # Group comments by file
    file_comments: dict[str, list[dict]] = {}
    
    for comment in comments:
        file_path = comment.get("file_path", "")
        if file_path not in file_comments:
            file_comments[file_path] = []
        file_comments[file_path].append(comment)
    
    # Build review comments
    review_comments = []
    
    for file_path, file_comments_list in file_comments.items():
        for comment in file_comments_list:
            line = comment.get("line_number")
            if line:
                review_comments.append({
                    "path": file_path,
                    "line": str(line),
                    "body": _format_comment_body(comment),
                })
    
    if not review_comments:
        return
    
    # Create review with comments
    try:
        summary = f"## CodeSage AI Review\n\n"
        summary += f"Found {len(comments)} issues:\n"
        
        severity_counts = {"error": 0, "warning": 0, "info": 0, "suggestion": 0}
        for c in comments:
            severity = c.get("severity", "info")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        for sev, count in severity_counts.items():
            if count > 0:
                summary += f"- {sev.capitalize()}: {count}\n"
        
        await github_service.create_review(
            owner,
            repo_name,
            pr.number,
            summary,
            "COMMENT",
            review_comments[:20],  # GitHub limits to 20 files per review
            installation_id,
        )
    except Exception:
        # Don't fail the review if posting to GitHub fails
        pass


def _format_comment_body(comment: dict) -> str:
    """Format a review comment with severity and suggestion."""
    
    severity = comment.get("severity", "info").upper()
    category = comment.get("category", "general")
    body = comment.get("body", "")
    suggestion = comment.get("suggestion")
    
    emoji = {
        "error": "\U0001F6AB",
        "warning": "\u26A0\uFE0F",
        "info": "\u2139\uFE0F",
        "suggestion": "\U0001F4A1",
    }.get(comment.get("severity", "info"), "\u2139\uFE0F")
    
    result = f"{emoji} **{severity}** [{category}]\n\n{body}"
    
    if suggestion:
        result += f"\n\n**Suggestion:**\n```\n{suggestion}\n```"
    
    return result
