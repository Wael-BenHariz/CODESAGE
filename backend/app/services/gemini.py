"""
Google Gemini AI Service
Handles code review generation using the Gemini API.
"""

import json
import re
from typing import Any, Optional

import httpx

from app.config import settings


class GeminiClient:
    """Raw async Gemini API client shared by review services and agents."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.usage_records: list[dict[str, int]] = []

    async def generate(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate Gemini text for a prompt."""

        response = await self.generate_with_usage(prompt, temperature, max_tokens)
        return response["text"]

    async def generate_with_usage(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Generate Gemini text and return token usage metadata."""

        url = f"{self.BASE_URL}/models/{self.model}:generateContent"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                        "topP": 0.95,
                        "topK": 40,
                    },
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                    ],
                },
                headers={"Content-Type": "application/json"},
            )

            response.raise_for_status()
            data = response.json()
            usage = data.get("usageMetadata", {})

            result = {
                "text": data["candidates"][0]["content"]["parts"][0]["text"],
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            }
            self.usage_records.append(
                {
                    "prompt_tokens": result["prompt_tokens"],
                    "completion_tokens": result["completion_tokens"],
                    "total_tokens": result["total_tokens"],
                }
            )
            return result

    def total_usage(self) -> dict[str, int]:
        """Return aggregate usage for calls made through this client instance."""

        return {
            "prompt_tokens": sum(record.get("prompt_tokens", 0) for record in self.usage_records),
            "completion_tokens": sum(record.get("completion_tokens", 0) for record in self.usage_records),
            "total_tokens": sum(record.get("total_tokens", 0) for record in self.usage_records),
        }


class GeminiService:
    """
    Google Gemini AI integration for code review.
    
    Features:
    - Configurable model and parameters
    - Code review prompt templates
    - Structured response parsing
    - Token usage tracking
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.max_tokens = max_tokens or settings.GEMINI_MAX_TOKENS
        self.temperature = temperature or settings.GEMINI_TEMPERATURE
        self.client = GeminiClient(api_key=self.api_key, model=self.model)

    async def generate_review(
        self,
        pr_title: str,
        pr_body: Optional[str],
        diff: str,
        language: str = "python",
        context: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Generate a code review for a pull request.
        
        Args:
            pr_title: Pull request title
            pr_body: Pull request description
            diff: Unified diff of changes
            language: Programming language of the changes
            context: Additional context (e.g., related files, commits)
            
        Returns:
            Review result with comments and summary
        """
        prompt = self._build_review_prompt(
            pr_title=pr_title,
            pr_body=pr_body,
            diff=diff,
            language=language,
            context=context,
        )
        
        response = await self._generate_content(prompt)
        return self._parse_review_response(response)

    async def review_file(
        self,
        filename: str,
        original_content: str,
        modified_content: str,
        language: str = "python",
    ) -> list[dict[str, Any]]:
        """
        Generate review comments for a single file.
        
        Args:
            filename: File path/name
            original_content: Original file content
            modified_content: Modified file content
            language: Programming language
            
        Returns:
            List of review comments with file path, line, severity, and message
        """
        prompt = self._build_file_review_prompt(
            filename=filename,
            original=original_content,
            modified=modified_content,
            language=language,
        )
        
        response = await self._generate_content(prompt)
        return self._parse_file_comments(response, filename)

    async def analyze_pr_summary(
        self,
        pr_title: str,
        pr_body: Optional[str],
        files_changed: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Generate a high-level PR summary.
        
        Args:
            pr_title: Pull request title
            pr_body: Pull request description
            files_changed: List of changed files with their changes
            
        Returns:
            PR summary with overall assessment
        """
        prompt = self._build_pr_summary_prompt(
            pr_title=pr_title,
            pr_body=pr_body,
            files_changed=files_changed,
        )
        
        response = await self._generate_content(prompt)
        return self._parse_pr_summary(response)

    # ==================== Private Methods ====================

    async def _generate_content(self, prompt: str) -> dict[str, Any]:
        """
        Generate content using the Gemini API.
        
        Args:
            prompt: Input prompt
            
        Returns:
            API response with generated content
        """
        return await self.client.generate_with_usage(
            prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    def _build_review_prompt(
        self,
        pr_title: str,
        pr_body: Optional[str],
        diff: str,
        language: str,
        context: Optional[str],
    ) -> str:
        """Build the code review prompt."""
        
        body_section = f"\n## Pull Request Description\n{pr_body}" if pr_body else "\n## Pull Request Description\n_No description provided._"
        context_section = f"\n## Additional Context\n{context}" if context else ""
        
        return f"""You are an expert code reviewer analyzing a pull request. Provide a thorough, constructive review focusing on:
1. Code quality and best practices
2. Potential bugs and security issues
3. Performance improvements
4. Code maintainability
5. Test coverage

## Pull Request Title
{pr_title}
{body_section}
{context_section}

## Programming Language
{language}

## Changes (Unified Diff)
{diff}

## Response Format
Provide your review in JSON format:

{{
    "summary": "Overall assessment of the changes (2-4 sentences)",
    "overall_severity": "info|warning|error",
    "comments": [
        {{
            "file_path": "path/to/file.py",
            "line_number": 42,
            "severity": "info|warning|error|suggestion",
            "category": "bug|security|performance|style|best_practice|general",
            "body": "Detailed comment about the issue",
            "suggestion": "Optional code suggestion if applicable"
        }}
    ],
    "statistics": {{
        "files_reviewed": 5,
        "issues_found": 8,
        "by_severity": {{"error": 1, "warning": 3, "info": 4}},
        "by_category": {{"bug": 2, "security": 1, "style": 3, "performance": 2}}
    }}
}}

IMPORTANT: Return ONLY valid JSON, no additional text or markdown formatting."""

    def _build_file_review_prompt(
        self,
        filename: str,
        original: str,
        modified: str,
        language: str,
    ) -> str:
        """Build prompt for single file review."""
        
        return f"""Review the following file changes and provide specific feedback.

Filename: {filename}
Language: {language}

## Original Content
```
{original}
```

## Modified Content
```
{modified}
```

Provide a JSON array of review comments:
[
    {{
        "line_number": 42,
        "severity": "info|warning|error|suggestion",
        "category": "bug|security|performance|style|best_practice|general",
        "body": "Comment text",
        "suggestion": "Optional fix suggestion"
    }}
]

Return ONLY valid JSON array, no additional text."""

    def _build_pr_summary_prompt(
        self,
        pr_title: str,
        pr_body: Optional[str],
        files_changed: list[dict[str, Any]],
    ) -> str:
        """Build prompt for PR summary."""
        
        files_list = "\n".join(
            f"- {f['filename']}: {f.get('status', 'modified')}"
            for f in files_changed[:20]  # Limit to first 20 files
        )
        
        return f"""Provide a concise summary of this pull request.

Title: {pr_title}
Description: {pr_body or "No description"}

Files Changed:
{files_list}

Provide a JSON summary:
{{
    "title": "Suggested PR title if changes are needed",
    "summary": "2-3 sentence summary of the changes",
    "type": "feature|bugfix|refactor|docs|test|chore",
    "breaking": false,
    "risks": ["Risk 1", "Risk 2"],
    "recommendations": ["Recommendation 1", "Recommendation 2"]
}}

Return ONLY valid JSON."""

    def _parse_review_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """Parse the AI response into structured review data."""
        
        try:
            text = response["text"]
            
            # Extract JSON from response (handle potential markdown code blocks)
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(text)
            
            # Add usage statistics
            data["usage"] = {
                "prompt_tokens": response.get("prompt_tokens", 0),
                "completion_tokens": response.get("completion_tokens", 0),
                "total_tokens": response.get("total_tokens", 0),
            }
            
            return data
            
        except (json.JSONDecodeError, KeyError) as e:
            # Return error structure if parsing fails
            return {
                "summary": text[:500] if text else "Failed to generate review",
                "overall_severity": "info",
                "comments": [],
                "statistics": {
                    "files_reviewed": 0,
                    "issues_found": 0,
                    "by_severity": {},
                    "by_category": {},
                },
                "error": str(e),
                "raw_response": text,
            }

    def _parse_file_comments(
        self,
        response: dict[str, Any],
        filename: str,
    ) -> list[dict[str, Any]]:
        """Parse file review comments."""
        
        try:
            text = response["text"]
            
            # Try to extract JSON array
            if text.startswith("["):
                comments = json.loads(text)
            else:
                json_match = re.search(r"\[[\s\S]*\]", text)
                if json_match:
                    comments = json.loads(json_match.group())
                else:
                    comments = []
            
            # Add filename to all comments
            for comment in comments:
                comment["file_path"] = filename
            
            return comments
            
        except json.JSONDecodeError:
            return []

    def _parse_pr_summary(self, response: dict[str, Any]) -> dict[str, Any]:
        """Parse PR summary response."""
        
        try:
            text = response["text"]
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "title": "",
                "summary": response.get("text", "")[:500],
                "type": "unknown",
                "breaking": False,
                "risks": [],
                "recommendations": [],
            }


# Global service instance
gemini_service = GeminiService()
