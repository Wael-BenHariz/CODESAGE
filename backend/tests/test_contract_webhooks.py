"""Black-box webhook boundary contract checks (WEBHOOK-*)."""

import hashlib
import hmac

import pytest


def signature(payload: bytes) -> str:
    digest = hmac.new(b"test-webhook-secret", payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected(client):
    response = await client.post(
        "/api/v1/webhooks/github",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "ping"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_signature_is_rejected(client):
    response = await client.post(
        "/api/v1/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "ping"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_signed_malformed_json_is_bad_request(client):
    body = b"{"
    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": signature(body), "X-GitHub-Event": "ping"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_unknown_signed_event_is_skipped(client):
    body = b"{}"
    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": signature(body), "X-GitHub-Event": "ping"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "skipped"}
