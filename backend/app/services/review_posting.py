"""Shared GitHub review-posting helpers (worker auto + API staged).

Step 6 of docs/PLAN_ROLES_SETTINGS_STAGED.md (Q3 decision):

- ``post_pr_review`` — the low-level HTTP call (moved here from the worker
  so the API can reuse it for the explicit staged post).
- ``build_review_body`` — Q3 body: base = ``edited_summary`` if set else
  ``summary``; **auto mode returns the base verbatim** (byte-identical to
  the pre-release behaviour — no findings, no sanitization, only a
  defensive GitHub-cap truncation); **staged mode** sanitizes the base and
  appends a ``## Findings`` section (non-dismissed comments only, grouped
  severity → file) capped at GitHub's 65 536-char body limit with a
  closing ``… N more findings, see CodeSage`` line.
- ``post_review_to_github`` — the shared entry point used by the worker
  (auto, called inline) and by the API (staged, Step 7): builds the body
  for the review's ``posting_mode`` and posts it.

Sanitization (Q3): all LLM/scanner-derived text is neutralized —
@mentions and #123 issue refs get a zero-width space (``# headings`` are
untouched), markdown link/image constructs are backslash-escaped, HTML
tags are stripped. Human-edited ordinary markdown (headings, bold, lists)
survives.
"""

import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import PullRequest, Repository, Review
from app.services.github_app import get_installation_token

# GitHub rejects bodies beyond this (422). Findings are truncated to fit;
# the final assembly gets one defensive cap before the send.
GITHUB_BODY_MAX_CHARS = 65_536

# Cap enforced by the Step 7 ``PATCH /reviews/{id}/summary`` endpoint on
# human-edited summaries (kept here as the single source of truth).
EDITED_SUMMARY_MAX_CHARS = 60_000

# Closing line appended when the findings section hits the body cap.
MORE_FINDINGS_TEMPLATE = "… {count} more findings, see CodeSage"

# Plan order: error > warning > suggestion > info. Unknown severities are
# bucketed into "info" (the vocabulary used by the specialist agents is
# exactly these four).
SEVERITY_ORDER = ("error", "warning", "suggestion", "info")

# Longest single finding message rendered (short message per Q3).
SHORT_MESSAGE_CHARS = 200

_ZERO_WIDTH_SPACE = "\u200b"
# Tag-like only: "<b>", "</script>", "<script src=...>" — but not "a < b".
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
# "@everyone" -> "@\u200Beveryone" (zero-width space AFTER the @).
_MENTION_RE = re.compile(r"@(?=\w)")
# "#123" issue ref -> "#\u200b123"; "# Heading" (hash + space) untouched.
_ISSUE_REF_RE = re.compile(r"#(?=\d)")
# Markdown link/image triggers: "[text](url)" and "![alt](url)".
_LINK_CHARS = ("[", "]", "(", ")", "!")


class ReviewPostError(Exception):
    """GitHub rejected the review POST (401/403/404/422)."""

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


def sanitize_generated_text(text: str) -> str:
    """Neutralize LLM/scanner-derived markdown content (Q3).

    @mentions and #123 issue refs are zero-width-spaced (``# Heading`` and
    ``# 123`` headings survive), link/image constructs are backslash
    escaped, HTML tags are stripped. Ordinary markdown (headings, bold,
    lists) renders unchanged.
    """
    if not text:
        return text
    text = _HTML_TAG_RE.sub("", text)
    text = _MENTION_RE.sub(f"@{_ZERO_WIDTH_SPACE}", text)
    text = _ISSUE_REF_RE.sub(f"#{_ZERO_WIDTH_SPACE}", text)
    for char in _LINK_CHARS:
        text = text.replace(char, "\\" + char)
    return text


def _cap_body(body: str) -> str:
    """Final defensive truncation before send (GitHub 65 536-char cap)."""
    if len(body) <= GITHUB_BODY_MAX_CHARS:
        return body
    return body[:GITHUB_BODY_MAX_CHARS]


def _finding_line(comment) -> str:
    """Render one finding: ``- `path:line` [tool] short message``."""
    path = comment.file_path or "?"
    location = f"{path}:{comment.line_number}" if comment.line_number else path
    # ``tool`` arrives with migration 015 (Step 7b) — generic badge until
    # the column exists so this module stays importable today.
    tool = getattr(comment, "tool", None) or "codesage"
    message = sanitize_generated_text(comment.body or "")
    if len(message) > SHORT_MESSAGE_CHARS:
        message = message[: SHORT_MESSAGE_CHARS - 1] + "…"
    return f"- `{location}` [{tool}] {message}"


def _render_finding_blocks(comments) -> list[str]:
    """Non-dismissed findings grouped severity → file, as render blocks.

    Each block is atomic for truncation: the first item of a group carries
    its ``### severity`` header, so a cut can never leave a dangling
    header.
    """
    buckets: dict[str, list] = {}
    for comment in comments:
        if comment.dismissed:
            continue
        severity = comment.severity if comment.severity in SEVERITY_ORDER else "info"
        buckets.setdefault(severity, []).append(comment)

    blocks: list[str] = []
    for severity in SEVERITY_ORDER:
        bucket = buckets.get(severity)
        if not bucket:
            continue
        bucket.sort(key=lambda c: (c.file_path or "", c.line_number or 0))
        for index, comment in enumerate(bucket):
            header = f"### {severity}\n" if index == 0 else ""
            blocks.append(header + _finding_line(comment))
    return blocks


def _assemble_findings(base: str, blocks: list[str]) -> str:
    """Join base + findings, truncating findings to the GitHub body cap."""
    prefix = f"{base}\n\n## Findings\n\n"
    included: list[str] = []
    for block in blocks:
        remaining_after = len(blocks) - len(included) - 1
        suffix = (
            f"\n{MORE_FINDINGS_TEMPLATE.format(count=remaining_after)}"
            if remaining_after
            else ""
        )
        candidate = prefix + "\n".join(included + [block])
        if len(candidate) + len(suffix) > GITHUB_BODY_MAX_CHARS:
            break
        included.append(block)

    body = prefix + "\n".join(included)
    remaining = len(blocks) - len(included)
    if remaining:
        body += f"\n{MORE_FINDINGS_TEMPLATE.format(count=remaining)}"
    return _cap_body(body)


def build_review_body(review: Review, *, include_findings: bool) -> str:
    """Build the GitHub review body for ``review`` per plan Q3.

    Auto mode (``include_findings=False``): the base summary verbatim —
    zero regression, no sanitization — plus a defensive cap. Staged mode:
    sanitized base + a ``## Findings`` section over the review's
    non-dismissed comments (caller must pass a review with ``comments``
    loaded; ``post_review_to_github`` refreshes them).
    """
    base = (
        review.edited_summary
        if review.edited_summary is not None
        else (review.summary or "")
    )
    if not include_findings:
        return _cap_body(base)

    blocks = _render_finding_blocks(review.comments)
    if not blocks:
        return _cap_body(sanitize_generated_text(base))
    return _assemble_findings(sanitize_generated_text(base), blocks)


async def post_review_to_github(
    db: AsyncSession,
    review: Review,
    *,
    pr: PullRequest | None = None,
    repo: Repository | None = None,
    installation_token: str | None = None,
) -> int:
    """Post the review's summary to GitHub (shared: worker + API).

    ``include_findings`` follows the review's ``posting_mode``: auto posts
    the plain summary (worker path), staged appends the Findings section
    (API path, Step 7). ``pr``/``repo``/``installation_token`` are loaded
    only when not provided (the worker passes its already-loaded rows and
    its already-minted token).
    """
    if pr is None:
        pr_result = await db.execute(
            select(PullRequest).where(PullRequest.id == review.pull_request_id)
        )
        pr = pr_result.scalar_one_or_none()
        if pr is None:
            raise ValueError("Pull request not found")

    if repo is None:
        repo_result = await db.execute(
            select(Repository)
            .options(selectinload(Repository.installation))
            .where(Repository.id == pr.repository_id)
        )
        repo = repo_result.scalar_one_or_none()
        if repo is None:
            raise ValueError("Repository not found")

    if installation_token is None:
        if repo.installation is None:
            raise ValueError("GitHub App installation not found")
        installation_token = await get_installation_token(
            repo.installation.installation_id
        )

    include_findings = review.posting_mode == "staged"
    if include_findings:
        # Fresh read: dismissals may have changed since the review loaded.
        await db.refresh(review, ["comments"])

    body = build_review_body(review, include_findings=include_findings)
    return await post_pr_review(
        full_name=repo.full_name,
        pr_number=pr.number,
        commit_sha=pr.head_sha,
        body=body,
        installation_token=installation_token,
    )
