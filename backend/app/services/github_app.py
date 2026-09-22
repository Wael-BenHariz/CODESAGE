"""GitHub App helpers for installation and repository access."""

from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

from app.config import settings

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
