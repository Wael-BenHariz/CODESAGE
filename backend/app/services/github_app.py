"""GitHub App helpers for installation and repository access."""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from jose import jwt

from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_ACCEPT_HEADER = "application/vnd.github+json"
GITHUB_API_VERSION = "2022-11-28"


def _normalized_private_key() -> str:
    return settings.GITHUB_APP_PRIVATE_KEY.replace("\\n", "\n").strip()


async def generate_app_jwt() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iat": int((now - timedelta(seconds=60)).timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "iss": str(settings.GITHUB_APP_ID),
    }
    return jwt.encode(payload, _normalized_private_key(), algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    app_jwt = await generate_app_jwt()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GITHUB_API_BASE_URL}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": GITHUB_ACCEPT_HEADER,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            raise ValueError("GitHub installation token was not returned")
        return token


async def fetch_file_content(
    full_name: str,
    file_path: str,
    ref: str,
    token: str,
) -> str | None:
    """Fetch the FULL text content of a file at ``ref`` (SonarQube needs
    complete files, not just diff patches).

    Uses the GitHub App installation token — never a user OAuth token.

    Returns:
        The decoded file content, or None when the file is missing (404),
        is a directory, or is binary/non-UTF-8 content.
    """
    encoded_path = quote(file_path, safe="/")
    url = f"{GITHUB_API_BASE_URL}/repos/{full_name}/contents/{encoded_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params={"ref": ref}, headers=headers)

    if response.status_code == 404:
        logger.debug("File not found on GitHub: %s@%s (%s)", file_path, ref, full_name)
        return None
    if response.status_code in (403, 422):
        # Unsupported content (directory, submodule, too large) or access
        # rule: skip the file instead of failing the whole review.
        logger.warning(
            "Skipping file %s for %s: HTTP %s %s",
            file_path,
            full_name,
            response.status_code,
            response.text[:200],
        )
        return None
    response.raise_for_status()

    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        logger.debug("Skipping binary file: %s (%s)", file_path, full_name)
        return None


def _has_next_page(link_header: str | None) -> bool:
    if not link_header:
        return False
    return 'rel="next"' in link_header


async def get_installation_repos(installation_id: int) -> list[dict]:
    token = await get_installation_token(installation_id)
    repos: list[dict] = []
    page = 1
    per_page = 100

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            response = await client.get(
                f"{GITHUB_API_BASE_URL}/installation/repositories",
                params={"per_page": per_page, "page": page},
                headers={
                    "Authorization": f"token {token}",
                    "Accept": GITHUB_ACCEPT_HEADER,
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
            )
            response.raise_for_status()
            payload = response.json()
            page_repos = payload.get("repositories", [])

            repos.extend(
                {
                    "id": repo["id"],
                    "name": repo["full_name"],
                    "private": repo.get("private", False),
                    "html_url": repo.get("html_url", ""),
                }
                for repo in page_repos
            )

            if not page_repos or not _has_next_page(response.headers.get("Link")):
                break
            page += 1

    return repos
