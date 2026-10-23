"""Unit tests for the repo-tenant-service HTTP client (services/repo_tenant.py).

The hook tests (test_repo_tenant_hook.py) assert WHEN enable/disable fire —
they patch these functions out. These tests exercise the HTTP layer itself
against a mock transport: success, HTTP failure, and transport failure.
The client must NEVER raise (best-effort by design: a watched repo must
save even when repo-tenant-service is down).
"""

import json
from uuid import uuid4

import httpx

import app.services.repo_tenant as repo_tenant

# Captured before any monkeypatching — after patching, httpx.AsyncClient
# *is* the factory, so the factory must not construct through that name.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_http(monkeypatch, routes):
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in routes:
            raise AssertionError(f"unexpected outbound request: {key}")
        return routes[key](request)

    def factory(*args, **kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_enable_repo_success_and_transport_failure(monkeypatch):
    captured = []
    fail_first = {"done": False}

    def responder(request):
        if not fail_first["done"]:
            fail_first["done"] = True
            raise httpx.ConnectError("repo-tenant down")
        captured.append(json.loads(request.content))
        return httpx.Response(204)

    _patch_http(monkeypatch, {("POST", "/api/v1/repos/internal/enable"): responder})

    owner = uuid4()
    # transport failure → swallowed, False
    assert (
        await repo_tenant.enable_repo(repo_id=7, full_name="o/r", owner_user_id=owner)
        is False
    )
    # success → True, camelCase payload for the Spring service
    assert (
        await repo_tenant.enable_repo(repo_id=7, full_name="o/r", owner_user_id=owner)
        is True
    )
    # no owner → null ownerUserId
    assert await repo_tenant.enable_repo(repo_id=8, full_name="o/r2") is True
    assert captured == [
        {"repoId": 7, "fullName": "o/r", "ownerUserId": str(owner)},
        {"repoId": 8, "fullName": "o/r2", "ownerUserId": None},
    ]


async def test_enable_repo_http_error_returns_false(monkeypatch):
    _patch_http(
        monkeypatch,
        {
            ("POST", "/api/v1/repos/internal/enable"): lambda r: httpx.Response(
                500, text="internal error"
            )
        },
    )
    assert await repo_tenant.enable_repo(repo_id=7, full_name="o/r") is False


async def test_disable_repo_success_and_transport_failure(monkeypatch):
    captured = []
    fail_first = {"done": False}

    def responder(request):
        if not fail_first["done"]:
            fail_first["done"] = True
            raise httpx.ConnectError("repo-tenant down")
        captured.append(json.loads(request.content))
        return httpx.Response(204)

    _patch_http(monkeypatch, {("POST", "/api/v1/repos/internal/disable"): responder})

    assert await repo_tenant.disable_repo(7) is False
    assert await repo_tenant.disable_repo(7) is True
    assert captured == [{"repoId": 7}]


async def test_disable_repo_http_error_returns_false(monkeypatch):
    _patch_http(
        monkeypatch,
        {
            ("POST", "/api/v1/repos/internal/disable"): lambda r: httpx.Response(
                503, text="unavailable"
            )
        },
    )
    assert await repo_tenant.disable_repo(7) is False
