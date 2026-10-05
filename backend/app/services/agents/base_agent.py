"""Base class for LLM-backed review agents."""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

import httpx

from app.services.agents.schemas import AgentResult, ReviewContext
from app.services.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# Hard ceiling for retry attempts that double the token budget
# (thinking-heavy models burn output tokens on reasoning; truncation is a
# common cause of unparseable JSON on large diffs).
RETRY_MAX_TOKENS = 8192

# Groq free-tier TPM (tokens per minute) per rolling window. Used to tell a
# transient window-overflow 413 (retry after backoff — the window drains
# within a minute) from a prompt that can never fit (fail fast).
GROQ_TPM_TOKENS = 8000


class BaseAgent(ABC):
    """Common Gemini invocation and tolerant JSON parsing for agents."""

    AGENT_NAME = "base"
    TEMPERATURE = 0.3
    MAX_TOKENS = 2048
    # Sleep seconds before retrying transient LLM errors:
    # 429 (rate limit) and 500/502/503/504 (temporary server issues).
    # Long quiet gaps: the free-tier RPM window is tight and 503 storms can
    # last a minute or more — short retries just keep re-triggering them.
    RATE_LIMIT_BACKOFF = (15, 30, 60)

    def __init__(self, client: BaseLLMClient):
        self.client = client

    async def run(self, context: ReviewContext) -> AgentResult:
        """Build the agent prompt, call the LLM once, and validate the result.

        Specialists are finding-refiners: with no findings in their domain
        there is nothing to validate, so the LLM call is skipped entirely
        (returns an empty, confident result) and the free-tier TPM budget
        is spent only on agents that have real work.
        """

        if not context.findings:
            return AgentResult(
                agent=self.AGENT_NAME,
                confidence=1.0,
                comments=[],
            )
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
        """Call the LLM and parse the response, retrying transient failures.

        - HTTP 429 / 500 / 502 / 503 / 504 (transient): sleep per
          RATE_LIMIT_BACKOFF and re-call with the same token budget —
          bounded by the backoff schedule. A 413 counts as transient when
          this prompt alone fits under GROQ_TPM_TOKENS (rolling-window
          overflow). Other HTTP errors raise at once.
        - Unparseable response: retry once with a doubled token budget
          (capped at RETRY_MAX_TOKENS) so truncation-caused failures get room
          to produce complete JSON.
        Every failure logs the raw response head for diagnosis instead of a
        bare JSONDecodeError.
        """

        last_error: Exception | None = None
        max_tokens = self.MAX_TOKENS
        rate_limit_retries = 0
        parse_attempts = 0
        http_attempts = 0

        while parse_attempts < 2:
            http_attempts += 1
            if http_attempts > 8:
                raise ValueError(
                    f"Agent {self.AGENT_NAME}: giving up after {http_attempts - 1} HTTP attempts: {last_error}"
                )
            try:
                raw = await self.client.complete(
                    prompt,
                    temperature=self.TEMPERATURE,
                    max_tokens=max_tokens,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                retryable = status == 429 or (
                    status is not None and 500 <= status <= 504
                )
                if status == 413 and len(prompt) // 4 < GROQ_TPM_TOKENS:
                    # Groq reports rolling-TPM overflow as 413 ("Limit 8000,
                    # Requested N" — N includes recent window usage, so it can
                    # exceed the limit even when this prompt alone fits).
                    # Transient: the window drains within a minute, so back off
                    # and retry. A prompt whose own estimate reaches the limit
                    # can never fit and falls through to raise.
                    retryable = True
                if retryable and rate_limit_retries < len(self.RATE_LIMIT_BACKOFF):
                    wait = self.RATE_LIMIT_BACKOFF[rate_limit_retries]
                    rate_limit_retries += 1
                    logger.warning(
                        "Agent %s: transient error (HTTP %s); retrying in %ds",
                        self.AGENT_NAME,
                        status,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

            # Any 200 proves the service is reachable again: give transient
            # backoff a fresh budget so an earlier 503/429 storm doesn't
            # starve the retries needed after this successful call.
            rate_limit_retries = 0

            parse_attempts += 1
            try:
                return self._parse_response(raw)
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                max_tokens = min(max_tokens * 2, RETRY_MAX_TOKENS)
                logger.warning(
                    "Agent %s: response parse failed (attempt %d/2, next max_tokens=%d): %s | raw head: %.500r",
                    self.AGENT_NAME,
                    parse_attempts,
                    max_tokens,
                    exc,
                    raw or "",
                )
        raise ValueError(
            f"Agent {self.AGENT_NAME}: unparseable LLM response after 2 attempts: {last_error}"
        ) from last_error

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse Gemini output into a dict.

        Tolerant pipeline — order matters:
        1. Reject empty responses with a clear error (retryable).
        2. Fast path: the whole response is already valid JSON. This MUST
           run BEFORE any fence stripping: a valid JSON object containing a
           markdown fence inside a string value (code samples in
           ``suggestion`` fields) would be destroyed by
           ``_strip_code_fences``, which returns only the fence's inner code
           and throws the surrounding JSON away — observed in production as
           two specialist agents failing on well-formed responses.
        3. Strip markdown code fences when the whole response is wrapped in
           one (```json ... ```) and parse that.
        4. Balanced-brace extraction (string-aware) over the raw and the
           stripped text so embedded or concatenated objects parse
           individually — the old greedy regex ``\\{[\\s\\S]*\\}`` merged
           ``{...}{...}`` into one invalid blob.
        """

        if not raw or not raw.strip():
            raise ValueError("LLM returned an empty response")

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        text = self._strip_code_fences(raw)
        if text != raw:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        for candidate in self._iter_json_objects(raw):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        if text != raw:
            for candidate in self._iter_json_objects(text):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        raise ValueError(
            f"no parseable JSON object found (response head: {raw[:200]!r})"
        )

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Return the content of the first ```json fenced block, else the text."""

        fenced = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)```", text)
        if fenced:
            return fenced.group(1).strip()
        return text

    @staticmethod
    def _iter_json_objects(text: str) -> Iterator[str]:
        """Yield every top-level balanced ``{...}`` block in ``text``.

        Tracks string literals and escape sequences so braces inside strings
        do not unbalance the scan. Truncated (unbalanced) output yields
        nothing, which surfaces as a clear parse failure instead of garbage.
        """

        depth = 0
        start: int | None = None
        in_string = False
        escape = False

        for i, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield text[start : i + 1]
                    start = None
