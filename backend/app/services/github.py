"""
GitHub Service
Handles GitHub OAuth, API interactions, and webhook management.
"""

import base64
import hashlib
import hmac
import time
from typing import Any, Optional

import httpx
from jose import jwt

from app.config import settings


class GitHubService:
    """
    GitHub API integration service.
    
    Handles:
    - OAuth flow
    - GitHub App authentication
    - Repository and PR operations
    - Webhook signature verification
    """

    BASE_URL = "https://api.github.com"
    ACCEPT_HEADER = "application/vnd.github+json"
    API_VERSION = "2022-11-28"

    def __init__(self):
        self.client_id = settings.GITHUB_CLIENT_ID
        self.client_secret = settings.GITHUB_CLIENT_SECRET
        self.callback_url = settings.GITHUB_CALLBACK_URL
        self.app_id = settings.GITHUB_APP_ID
        self.app_private_key = settings.GITHUB_APP_PRIVATE_KEY
        self.webhook_secret = settings.GITHUB_WEBHOOK_SECRET

    # ==================== OAuth ====================

    def get_oauth_login_url(self, state: str, redirect_url: Optional[str] = None, prompt_select: bool = True) -> str:
        """
        Generate GitHub OAuth authorization URL.
        
        Args:
            state: CSRF protection state string
            redirect_url: URL to redirect after authorization
            prompt_select: If True, forces GitHub account chooser
            
        Returns:
            GitHub authorization URL
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.callback_url,
            "scope": "read:user user:email repo",
            "state": state,
        }
        
        if prompt_select:
            params["prompt"] = "select_account"
        
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"https://github.com/login/oauth/authorize?{query}"

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """
        Exchange authorization code for OAuth access token.
        
        Args:
            code: Authorization code from GitHub callback
            
        Returns:
            Token response with access_token, refresh_token, etc.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.callback_url,
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()

    async def refresh_oauth_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh an expired OAuth access token.
        
        Args:
            refresh_token: OAuth refresh token
            
        Returns:
            New token response
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """
        Get authenticated user's information.
        
        Args:
            access_token: GitHub OAuth access token
            
        Returns:
            GitHub user data
        """
        return await self._get("/user", access_token)

    async def get_user_emails(self, access_token: str) -> list[dict[str, Any]]:
        """
        Get authenticated user's email addresses.
        
        Args:
            access_token: GitHub OAuth access token
            
        Returns:
            List of email objects
        """
        return await self._get("/user/emails", access_token)

    # ==================== GitHub App ====================

    def create_app_jwt(self) -> str:
        """
        Create a JWT for GitHub App authentication.
        
        Returns:
            Signed JWT token
        """
        now = int(time.time())
        
        payload = {
            "iat": now,
            "exp": now + 600,  # 10 minutes max
            "iss": self.app_id,
        }
        
        return jwt.encode(payload, self.app_private_key, algorithm="RS256")

    async def get_installation_token(self, installation_id: int) -> dict[str, Any]:
        """
        Get installation access token for a GitHub App.
        
        Args:
            installation_id: GitHub App installation ID
            
        Returns:
            Installation token response
        """
        jwt_token = self.create_app_jwt()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": self.ACCEPT_HEADER,
                    "X-GitHub-Api-Version": self.API_VERSION,
                },
            )
            response.raise_for_status()
            return response.json()

    # ==================== API Requests ====================

    async def _get(
        self,
        path: str,
        token: str,
        params: Optional[dict] = None,
    ) -> Any:
        """Make authenticated GET request to GitHub API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}{path}",
                params=params,
                headers=self._headers(token),
            )
            response.raise_for_status()
            return response.json()

    async def _post(
        self,
        path: str,
        token: str,
        data: Optional[dict] = None,
    ) -> Any:
        """Make authenticated POST request to GitHub API."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}{path}",
                json=data,
                headers=self._headers(token),
            )
            response.raise_for_status()
            return response.json()

    async def _patch(
        self,
        path: str,
        token: str,
        data: dict,
    ) -> Any:
        """Make authenticated PATCH request to GitHub API."""
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.BASE_URL}{path}",
                json=data,
                headers=self._headers(token),
            )
            response.raise_for_status()
            return response.json()

    async def _delete(
        self,
        path: str,
        token: str,
    ) -> None:
        """Make authenticated DELETE request to GitHub API."""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.BASE_URL}{path}",
                headers=self._headers(token),
            )
            response.raise_for_status()

    def _headers(self, token: str) -> dict[str, str]:
        """Build request headers."""
        return {
            "Authorization": f"Bearer {token}",
            "Accept": self.ACCEPT_HEADER,
            "X-GitHub-Api-Version": self.API_VERSION,
        }

    # ==================== Repository Operations ====================

    async def get_user_repos(self, access_token: str, per_page: int = 100) -> list[dict[str, Any]]:
        """
        Get list of repositories accessible by the authenticated user.
        
        Args:
            access_token: GitHub OAuth access token
            per_page: Results per page (max 100)
            
        Returns:
            List of repository data
        """
        repos = []
        page = 1
        
        while True:
            data = await self._get("/user/repos", access_token, {
                "per_page": per_page,
                "page": page,
                "sort": "updated",
                "affiliation": "owner,collaborator,organization_member",
            })
            if not data:
                break
            repos.extend(data)
            if len(data) < per_page:
                break
            page += 1
        
        return repos

    async def get_repository(
        self,
        owner: str,
        repo: str,
        installation_id: int,
    ) -> dict[str, Any]:
        """
        Get repository information.
        
        Args:
            owner: Repository owner
            repo: Repository name
            installation_id: GitHub App installation ID
            
        Returns:
            Repository data
        """
        token = await self._get_installation_token(installation_id)
        return await self._get(f"/repos/{owner}/{repo}", token)

    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str,
        installation_id: int,
    ) -> Optional[str]:
        """
        Get file content from a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: File path in repository
            ref: Git reference (branch, commit, tag)
            installation_id: GitHub App installation ID
            
        Returns:
            Decoded file content or None if not found
        """
        token = await self._get_installation_token(installation_id)
        
        try:
            data = await self._get(f"/repos/{owner}/{repo}/contents/{path}", token, {"ref": ref})
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8")
            return data.get("content")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
    ) -> dict[str, Any]:
        """
        Get pull request information.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            installation_id: GitHub App installation ID
            
        Returns:
            Pull request data
        """
        token = await self._get_installation_token(installation_id)
        return await self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}", token)

    async def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get files changed in a pull request.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            installation_id: GitHub App installation ID
            per_page: Results per page (max 100)
            
        Returns:
            List of changed files
        """
        token = await self._get_installation_token(installation_id)
        return await self._get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
            token,
            {"per_page": per_page},
        )

    async def get_pull_request_commits(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
    ) -> list[dict[str, Any]]:
        """
        Get commits in a pull request.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            installation_id: GitHub App installation ID
            
        Returns:
            List of commits
        """
        token = await self._get_installation_token(installation_id)
        return await self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}/commits", token)

    async def get_commit_diff(
        self,
        owner: str,
        repo: str,
        sha: str,
        installation_id: int,
    ) -> str:
        """
        Get diff for a commit.
        
        Args:
            owner: Repository owner
            repo: Repository name
            sha: Commit SHA
            installation_id: GitHub App installation ID
            
        Returns:
            Commit diff as string
        """
        token = await self._get_installation_token(installation_id)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/commits/{sha}",
                params={"accept": "application/vnd.github.v3.diff"},
                headers=self._headers(token),
            )
            response.raise_for_status()
            return response.text

    async def get_comparison(
        self,
        owner: str,
        repo: str,
        base: str,
        head: str,
        installation_id: int,
    ) -> dict[str, Any]:
        """
        Compare two branches/commits.
        
        Args:
            owner: Repository owner
            repo: Repository name
            base: Base branch/SHA
            head: Head branch/SHA
            installation_id: GitHub App installation ID
            
        Returns:
            Comparison data including files changed
        """
        token = await self._get_installation_token(installation_id)
        return await self._get(f"/repos/{owner}/{repo}/compare/{base}...{head}", token)

    # ==================== Review Comments ====================

    async def create_review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        installation_id: int,
    ) -> dict[str, Any]:
        """
        Create a review comment on a pull request.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            body: Comment body
            commit_id: Commit SHA to comment on
            path: File path
            line: Line number
            installation_id: GitHub App installation ID
            
        Returns:
            Created comment data
        """
        token = await self._get_installation_token(installation_id)
        
        data = {
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
            "side": "RIGHT",  # Comment on the added lines
        }
        
        return await self._post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            token,
            data,
        )

    async def create_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str,
        comments: list[dict],
        installation_id: int,
    ) -> dict[str, Any]:
        """
        Create a review on a pull request with inline comments.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            body: Review summary
            event: Review event (COMMENT, APPROVE, REQUEST_CHANGES)
            comments: List of inline comments
            installation_id: GitHub App installation ID
            
        Returns:
            Created review data
        """
        token = await self._get_installation_token(installation_id)
        
        data = {
            "body": body,
            "event": event,
            "comments": comments,
        }
        
        return await self._post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            token,
            data,
        )

    # ==================== Webhooks ====================

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        """
        Verify GitHub webhook signature.
        
        Args:
            payload: Raw request body
            signature: X-Hub-Signature-256 header value
            timestamp: X-Hub-Signature-256 timestamp (optional for older webhooks)
            
        Returns:
            True if signature is valid
        """
        if not signature:
            return False
        
        # Handle both sha256= and timestamp,sha256= formats
        if signature.startswith("sha256="):
            expected = signature[7:]
        else:
            return False
        
        # Compute HMAC
        mac = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        )
        computed = mac.hexdigest()
        
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(computed, expected)

    def generate_webhook_signature(self, payload: bytes) -> str:
        """
        Generate a webhook signature for testing/debugging.
        
        Args:
            payload: Request body
            
        Returns:
            HMAC signature in format sha256=xxx
        """
        mac = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        )
        return f"sha256={mac.hexdigest()}"

    # ==================== App Installation ====================

    async def get_app_installation(self, installation_id: int) -> dict[str, Any]:
        """
        Get installation details for the GitHub App.
        
        Args:
            installation_id: Installation ID
            
        Returns:
            Installation data
        """
        jwt_token = self.create_app_jwt()
        return await self._get(f"/app/installations/{installation_id}", jwt_token)

    async def get_installed_repos(self, installation_id: int) -> list[dict[str, Any]]:
        """
        Get repositories accessible to an installation.
        
        Args:
            installation_id: Installation ID
            
        Returns:
            List of repository data
        """
        jwt_token = self.create_app_jwt()
        
        repos = []
        page = 1
        
        while True:
            data = await self._get(
                f"/app/installations/{installation_id}/repositories",
                jwt_token,
                {"per_page": 100, "page": page},
            )
            repos.extend(data.get("repositories", []))
            
            if not data.get("repositories") or len(data["repositories"]) < 100:
                break
            page += 1
        
        return repos

    async def create_repository_webhook(
        self,
        owner: str,
        repo: str,
        installation_id: int,
    ) -> dict[str, Any]:
        """
        Create a webhook on a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            installation_id: Installation ID
            
        Returns:
            Created webhook data
        """
        token = await self._get_installation_token(installation_id)
        
        # This would be called with your actual webhook URL
        webhook_url = f"https://your-domain.com/api/v1/webhooks/github"
        
        data = {
            "name": "web",
            "active": True,
            "events": ["pull_request", "push"],
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": self.webhook_secret,
            },
        }
        
        return await self._post(f"/repos/{owner}/{repo}/hooks", token, data)

    async def _get_installation_token(self, installation_id: int) -> str:
        """Get cached installation token."""
        response = await self.get_installation_token(installation_id)
        return response["token"]


# Global service instance
github_service = GitHubService()