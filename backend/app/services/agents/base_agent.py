"""Base class for Gemini-backed review agents."""

from abc import ABC, abstractmethod
import json
import re
from typing import Any

from app.services.agents.schemas import AgentResult, ReviewContext
from app.services.gemini import GeminiClient


class BaseAgent(ABC):
    """Common Gemini invocation and tolerant JSON parsing for agents."""

    AGENT_NAME = "base"
    TEMPERATURE = 0.3
    MAX_TOKENS = 2048

    def __init__(self, gemini_client: GeminiClient):
        self.gemini_client = gemini_client

    async def run(self, context: ReviewContext) -> AgentResult:
        """Build the agent prompt, call Gemini once, and validate the result."""

        prompt = self._build_prompt(context)
        data = await self._call_llm(prompt)
        data.setdefault("agent", self.AGENT_NAME)
        data.setdefault("confidence", 0.0)
        data.setdefault("comments", [])
        return AgentResult.model_validate(data)

    @abstractmethod
    def _build_prompt(self, context: ReviewContext) -> str:
        """Build a specialist prompt for the provided review context."""

    async def _call_llm(self, prompt: str) -> dict[str, Any]:
        raw = await self.gemini_client.generate(
            prompt,
            temperature=self.TEMPERATURE,
            max_tokens=self.MAX_TOKENS,
        )
        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse Gemini text using the existing tolerant JSON object extraction."""

        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(raw)
