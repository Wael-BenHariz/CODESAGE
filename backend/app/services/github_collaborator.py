"""GitHub collaborator helper (repo-scoped invitations).

The GitHub App can add a user to a repository with the "Add repository
collaborator" endpoint — ``PUT /repos/{owner}/{repo}/collaborators/{username}``
— which requires the App to hold the ``administration`` permission on the
installation (org **Settings → GitHub Apps → Repository access**).

Permission mapping (one role for the whole repository selection):

=================  ==================
CodeSage role      GitHub permission
=================  ==================
DEVELOPER          push   (write)
REVIEWER           triage (review issues/PRs, no push)
=================  ==================

Every function here is **best-effort**: the caller (the invitation
accept flow) records whatever comes back and never fails the accept
because GitHub said no.
"""

import logging

import httpx

from app.services.github_app import (
    GITHUB_ACCEPT_HEADER,
    GITHUB_API_BASE_URL,
    GITHUB_API_VERSION,
)

logger = logging.getLogger(__name__)

#: One role → one GitHub permission for every repo in the invitation.
ROLE_TO_GITHUB_PERMISSION: dict[str, str] = {
    "DEVELOPER": "push",
    "REVIEWER": "triage",
}

_REQUEST_TIMEOUT = 10.0


async def ensure_collaborator(
    *,
    installation_token: str,
    full_name: str,
    username: str,
    permission: str,
) -> tuple[bool, str | None]:
    """Add (or confirm) ``username`` as a collaborator on ``full_name``.

    Returns ``(ok, error_message)``:

    - **201** — added now → ``(True, None)``
    - **204** — already a collaborator with equal/higher permission →
      ``(True, None)`` (the "already a collaborator" case is a success)
    - **403/404/422/5xx/network** — ``(False, <human-readable reason>)``

    Never raises: transport errors are converted into the error half of
    the tuple so the caller can log/store them and move on.
    """
    url = f"{GITHUB_API_BASE_URL}/repos/{full_name}/collaborators/{username}"
    headers = {
        "Authorization": f"token {installation_token}",
        "Accept": GITHUB_ACCEPT_HEADER,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.put(
                url, json={"permission": permission}, headers=headers
            )
    except httpx.HTTPError as exc:
        logger.warning("GitHub collaborator call failed for %s: %s", full_name, exc)
        return False, f"GitHub request failed: {exc}"

    if response.status_code in (201, 204):
        return True, None

    try:
        message = response.json().get("message", response.text)
    except Exception:  # noqa: BLE001 — non-JSON error body (proxy pages, …)
        message = response.text[:200]

    if response.status_code == 403:
        detail = (
            f"HTTP 403 {message} — the GitHub App needs the "
            "'administration' repository permission"
        )
    elif response.status_code == 404:
        detail = f"HTTP 404 {message} (repository or user not found)"
    else:
        detail = f"HTTP {response.status_code} {message}"

    logger.warning(
        "Could not add %s as %s collaborator on %s: %s",
        username,
        permission,
        full_name,
        detail,
    )
    return False, detail
