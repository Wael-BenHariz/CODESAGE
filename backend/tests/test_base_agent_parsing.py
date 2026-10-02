"""Tolerant LLM-response parsing in ``BaseAgent`` (Fix: raw JSON first).

Regression cover for the production failure where a perfectly valid JSON
response was destroyed by fence stripping: the model embedded a markdown
code fence inside a string value (a code sample in ``suggestion``), the
fence regex extracted only the inner code, and the agent reported
``no parseable JSON object found`` — killing 2 of 5 specialists on a run.

Order under test:
1. whole response is valid JSON (even with "```" inside a string) → parse
2. whole response wrapped in a ``` fence → strip then parse
3. JSON embedded in prose / concatenated objects → balanced extraction
4. empty / unparseable input → ValueError with a diagnosable message
"""

import json

from app.services.agents import ReviewContext, SecurityAgent
from app.services.agents.base_agent import BaseAgent
from app.services.llm_client import BaseLLMClient


class _StubLLM(BaseLLMClient):
    """Returns canned responses in order; records every prompt."""

    def __init__(self, responses: list[str]):
        super().__init__(api_key="test-key", model="fake-model")
        self._responses = list(responses)
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return self.model

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


def _security_payload() -> dict:
    return {
        "agent": "security",
        "confidence": 0.95,
        "comments": [
            {
                "file_path": "test.java",
                "line_number": 15,
                "severity": "error",
                "category": "security",
                "body": "Hard-coded secrets",
                "suggestion": 'Load from env:\n```java\nString sql = "SELECT *";\n```',
            }
        ],
    }


# --- 1. raw valid JSON wins, even with a fence inside a string value ---------


def test_valid_json_containing_code_fence_inside_string_parses():
    """The production regression: valid JSON, fence lives IN a string."""

    raw = json.dumps(_security_payload())
    assert "```" in raw  # fence present inside the suggestion string

    parsed = SecurityAgent(_StubLLM([]))._parse_response(raw)
    assert parsed["agent"] == "security"
    assert parsed["comments"][0]["suggestion"].startswith("Load from env:")


def test_fence_in_string_is_why_raw_must_be_tried_first():
    """Document the mechanism: stripping THIS response destroys the JSON.

    ``_strip_code_fences`` matches the first ``` pair — which lives inside
    the suggestion string — and returns only the inner code. If the parser
    ever strips before trying raw again, this test fails loudly.
    """

    raw = json.dumps(_security_payload())
    stripped = BaseAgent._strip_code_fences(raw)
    assert stripped != raw  # the in-string fence engaged the regex
    assert "agent" not in stripped  # the JSON object was thrown away
    try:
        json.loads(stripped)
        raise AssertionError("fence-stripping is expected to destroy this input")
    except json.JSONDecodeError:
        pass


# --- 2. whole-response fences still strip ------------------------------------


def test_whole_response_wrapped_in_json_fence_parses():
    payload = {"agent": "style", "confidence": 0.5, "comments": []}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    parsed = SecurityAgent(_StubLLM([]))._parse_response(fenced)
    assert parsed["agent"] == "style"


def test_fence_without_language_tag_parses():
    payload = {"agent": "complexity", "confidence": 0.4, "comments": []}
    fenced = f"```\n{json.dumps(payload)}\n```"
    parsed = SecurityAgent(_StubLLM([]))._parse_response(fenced)
    assert parsed["agent"] == "complexity"


# --- 3. embedded / concatenated objects --------------------------------------


def test_json_embedded_in_prose_parses():
    payload = {"agent": "performance", "confidence": 0.7, "comments": []}
    noisy = f"Here is my review:\n{json.dumps(payload)}\nHope that helps!"
    parsed = SecurityAgent(_StubLLM([]))._parse_response(noisy)
    assert parsed["agent"] == "performance"


def test_concatenated_objects_yield_the_first():
    first = {"agent": "security", "confidence": 0.9, "comments": []}
    second = {"agent": "style", "confidence": 0.1, "comments": []}
    parsed = SecurityAgent(_StubLLM([]))._parse_response(
        json.dumps(first) + json.dumps(second)
    )
    assert parsed["agent"] == "security"


# --- 4. clear errors for unusable input --------------------------------------


def test_empty_response_raises_retryable_error():
    agent = SecurityAgent(_StubLLM([]))
    for empty in ("", "   ", "\n\t"):
        try:
            agent._parse_response(empty)
            raise AssertionError("empty input must raise")
        except ValueError as exc:
            assert "empty response" in str(exc)


def test_unparseable_response_mentions_head_and_raw_prefix():
    agent = SecurityAgent(_StubLLM([]))
    try:
        agent._parse_response("no json here at all, just prose")
        raise AssertionError("prose must raise")
    except ValueError as exc:
        assert "no parseable JSON object found" in str(exc)
        # The head must come from the RAW text (diagnosable), not from a
        # fence-stripped fragment.
        assert "no json here" in str(exc)


# --- end-to-end: no retry wasted on a parseable response ----------------------


async def test_run_parses_fence_in_string_response_without_retrying():
    """A fence-in-string response must succeed on attempt 1 (no retry)."""

    stub = _StubLLM([json.dumps(_security_payload())])
    agent = SecurityAgent(stub)
    context = ReviewContext(
        pr_title="Add endpoint",
        language="java",
        diff="",
        findings=[],  # parsing is exercised regardless of slice contents
    )
    # Call the LLM path directly: run() short-circuits empty slices (Fix C)
    # and we want to prove _call_llm parses this response first try.
    result = await agent._call_llm(agent._build_prompt(context))
    assert result["agent"] == "security"
    assert len(stub.prompts) == 1  # no parse-retry burned


def test_base_agent_helpers_still_available():
    """Sanity: fence stripping and balanced scan remain part of the pipeline."""
    assert BaseAgent._strip_code_fences("```json\n{}\n```") == "{}"
    assert list(BaseAgent._iter_json_objects('x {"a": 1} y')) == ['{"a": 1}']
