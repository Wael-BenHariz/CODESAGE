"""Failure handling contract for the multi-agent review pipeline."""

import pytest

from app.services.agents.specialist_agents import SecurityAgent


def test_json_extractor_rejects_unstructured_text():
    agent = SecurityAgent(client=None)
    with pytest.raises(ValueError, match="no parseable JSON object"):
        agent._parse_response("plain text without an object")


def test_json_extractor_accepts_embedded_object():
    result = SecurityAgent(client=None)._parse_response(
        'prefix {"comments": []} suffix'
    )
    assert result == {"comments": []}
