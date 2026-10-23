"""Unit tests for the SonarQube client (services/sonarqube.py).

Everything remote is faked:
- httpx: the module builds ``httpx.AsyncClient`` at call time, so a
  factory injected over ``httpx.AsyncClient`` hands every API call to
  ``httpx.MockTransport``;
- the scanner subprocess: ``asyncio.create_subprocess_exec`` is
  patched per test;
- time/settings: patched on the ``sonarqube`` module only.

Covers the project lifecycle, temp workspace, scanner, polling, issue
pagination and the master ``scan()`` — the fault-isolation paths the
worker relies on when SonarQube is down.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

import app.services.sonarqube as sonarqube
from app.services.sonarqube import (
    AGENT_BUCKETS,
    SonarQubeError,
    SonarQubeTimeoutError,
    create_project,
    delete_project,
    get_issues,
    group_issues_by_agent,
    run_scanner,
    scan,
    wait_for_analysis,
    write_files_to_temp_dir,
)

# Captured before any monkeypatching — after patching, httpx.AsyncClient
# *is* the factory, so the factory must not construct through that name.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_settings(monkeypatch, token="test-token", timeout=5, poll=0):
    monkeypatch.setattr(
        sonarqube,
        "settings",
        SimpleNamespace(
            SONARQUBE_TOKEN=token,
            SONARQUBE_URL="http://sonar.test",
            SONARQUBE_ANALYSIS_TIMEOUT=timeout,
            SONARQUBE_POLL_INTERVAL=poll,
        ),
    )


def _patch_http(monkeypatch, routes):
    """Intercept every outbound call; ``routes`` keyed by (method, path)."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in routes:
            raise AssertionError(f"unexpected outbound request: {key}")
        return routes[key](request)

    def factory(*args, **kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _ce(status, task_id="task-1"):
    return httpx.Response(200, json={"tasks": [{"status": status, "id": task_id}]})


class _FakeProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout, self._stderr = stdout, stderr
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


# --- auth -------------------------------------------------------------------


def test_auth_headers_requires_token(monkeypatch):
    _patch_settings(monkeypatch, token="")
    with pytest.raises(SonarQubeError, match="SONARQUBE_TOKEN is not configured"):
        sonarqube._auth_headers()


def test_auth_headers_bearer(monkeypatch):
    _patch_settings(monkeypatch, token="tok-123")
    assert sonarqube._auth_headers() == {"Authorization": "Bearer tok-123"}


# --- project lifecycle ------------------------------------------------------


async def test_create_project_success_and_tolerates_already_exists(monkeypatch):
    _patch_settings(monkeypatch)
    seen = []

    def responder(request):
        seen.append(request.url.params.get("project"))
        if len(seen) == 1:
            return httpx.Response(200)
        return httpx.Response(400, text="Project already exists")

    _patch_http(monkeypatch, {("POST", "/api/projects/create"): responder})
    await create_project("key-a", "name-a")
    await create_project("key-a", "name-a")  # tolerated, no raise
    assert seen == ["key-a", "key-a"]


async def test_create_project_failure_raises(monkeypatch):
    _patch_settings(monkeypatch)
    _patch_http(
        monkeypatch,
        {("POST", "/api/projects/create"): lambda r: httpx.Response(404, text="nope")},
    )
    with pytest.raises(SonarQubeError, match="Failed to create SonarQube project"):
        await create_project("key-a", "name-a")


async def test_delete_project_never_raises(monkeypatch):
    """Bad HTTP status and transport failure are both warnings only."""
    _patch_settings(monkeypatch)
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        raise httpx.ConnectError("repo down")

    _patch_http(monkeypatch, {("POST", "/api/projects/delete"): responder})
    await delete_project("key-a")  # HTTP 500 → warning
    await delete_project("key-a")  # transport error → warning
    assert calls["n"] == 2


# --- temp workspace ---------------------------------------------------------


def test_write_files_to_temp_dir_writes_and_rejects(tmp_path):
    root = str(tmp_path)
    write_files_to_temp_dir(
        [
            {"filename": "src/deep/a.py", "content": "print(1)"},
            {"filename": "empty.py", "content": ""},  # skipped
            {"filename": "", "content": "x"},  # skipped
            {"filename": "../../evil.py", "content": "x"},  # traversal skipped
        ],
        root,
    )
    assert (tmp_path / "src" / "deep" / "a.py").read_text() == "print(1)"
    assert not (tmp_path / "empty.py").exists()
    assert not (tmp_path.parent / "evil.py").exists()


# --- scanner ----------------------------------------------------------------


async def test_run_scanner_success(monkeypatch):
    _patch_settings(monkeypatch)
    captured = {}

    async def fake_exec(*command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_scanner("proj", "/tmp/dir", "python")
    assert captured["command"][0] == "sonar-scanner"
    assert "-Dsonar.projectKey=proj" in captured["command"]
    assert "-Dsonar.host.url=http://sonar.test" in captured["command"]
    assert captured["kwargs"]["cwd"] == "/tmp/dir"


async def test_run_scanner_nonzero_exit_raises_with_tails(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_exec(*command, **kwargs):
        return _FakeProcess(
            returncode=1, stderr=b"err line1\nerr line2", stdout=b"out line"
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SonarQubeError, match="exited with code 1"):
        await run_scanner("proj", "/tmp/dir", "python")


async def test_run_scanner_launch_oserror_raises(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_exec(*command, **kwargs):
        raise OSError("sonar-scanner not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SonarQubeError, match="failed to launch"):
        await run_scanner("proj", "/tmp/dir", "python")


async def test_run_scanner_timeout_kills_and_raises(monkeypatch):
    _patch_settings(monkeypatch)
    proc = _FakeProcess()

    async def fake_exec(*command, **kwargs):
        return proc

    async def fake_wait_for(awaitable, timeout=None):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()  # never awaited otherwise
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    with pytest.raises(SonarQubeTimeoutError, match="timed out"):
        await run_scanner("proj", "/tmp/dir", "python")
    assert proc.killed is True


# --- analysis polling -------------------------------------------------------


async def test_wait_for_analysis_success(monkeypatch):
    _patch_settings(monkeypatch)
    _patch_http(monkeypatch, {("GET", "/api/ce/activity"): lambda r: _ce("SUCCESS")})
    assert await wait_for_analysis("proj") == "task-1"


async def test_wait_for_analysis_polls_pending_then_succeeds(monkeypatch):
    _patch_settings(monkeypatch)
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        return _ce("PENDING") if calls["n"] == 1 else _ce("SUCCESS")

    _patch_http(monkeypatch, {("GET", "/api/ce/activity"): responder})
    assert await wait_for_analysis("proj") == "task-1"
    assert calls["n"] == 2


async def test_wait_for_analysis_failed_status_raises(monkeypatch):
    _patch_settings(monkeypatch)
    _patch_http(
        monkeypatch,
        {("GET", "/api/ce/activity"): lambda r: _ce("FAILED", "task-9")},
    )
    with pytest.raises(SonarQubeError, match="Analysis failed for project"):
        await wait_for_analysis("proj")


async def test_wait_for_analysis_http_error_raises(monkeypatch):
    _patch_settings(monkeypatch)
    _patch_http(
        monkeypatch,
        {
            ("GET", "/api/ce/activity"): lambda r: httpx.Response(
                503, text="unavailable"
            )
        },
    )
    with pytest.raises(SonarQubeError, match="Failed to poll analysis"):
        await wait_for_analysis("proj")


async def test_wait_for_analysis_timeout_raises(monkeypatch):
    _patch_settings(monkeypatch, timeout=5)
    _patch_http(
        monkeypatch,
        {
            ("GET", "/api/ce/activity"): lambda r: httpx.Response(
                200, json={"tasks": []}
            )
        },
    )
    # deadline = 0 + 5; the next tick is far beyond it.
    ticks = iter([0.0, 10_000.0])
    monkeypatch.setattr(
        sonarqube, "time", SimpleNamespace(monotonic=lambda: next(ticks))
    )
    with pytest.raises(SonarQubeTimeoutError, match="did not complete within"):
        await wait_for_analysis("proj")


# --- issues -----------------------------------------------------------------


async def test_get_issues_paginates_and_parses(monkeypatch):
    _patch_settings(monkeypatch)
    raw_issue = {
        "key": "i1",
        "rule": "python:S100",
        "severity": "major",
        "type": "code_smell",
        "component": "proj:src/a.py",
        "line": 7,
        "message": "bad name",
        "effort": "5min",
        "tags": ["convention"],
    }

    def responder(request):
        if request.url.params.get("p") == "1":
            return httpx.Response(200, json={"total": 600, "issues": []})
        return httpx.Response(200, json={"total": 600, "issues": [raw_issue]})

    _patch_http(monkeypatch, {("GET", "/api/issues/search"): responder})
    issues = await get_issues("proj")
    assert len(issues) == 1
    issue = issues[0]
    assert issue.component == "src/a.py"  # project-key prefix stripped
    assert issue.severity == "MAJOR"  # upper-cased
    assert issue.line == 7
    assert issue.tags == ["convention"]


async def test_get_issues_http_error_raises(monkeypatch):
    _patch_settings(monkeypatch)
    _patch_http(
        monkeypatch,
        {("GET", "/api/issues/search"): lambda r: httpx.Response(500, text="err")},
    )
    with pytest.raises(SonarQubeError, match="Failed to fetch issues"):
        await get_issues("proj")


# --- grouping ---------------------------------------------------------------


def test_group_issues_by_agent_first_matching_bucket_wins():
    def issue(key, type_="CODE_SMELL", tags=()):
        return sonarqube.SonarIssue(
            key=key,
            rule="r",
            severity="MAJOR",
            type=type_,
            component="a.py",
            line=1,
            message="m",
            effort=None,
            tags=list(tags),
        )

    issues = [
        issue("s", type_="VULNERABILITY"),
        issue("c", tags=["brain-overload"]),
        issue("p", tags=["performance"]),
        issue("t", tags=["unused"]),
        issue("st"),
    ]
    grouped = group_issues_by_agent(issues)
    assert set(grouped) == set(AGENT_BUCKETS)
    assert [i.key for i in grouped["security"]] == ["s"]
    assert [i.key for i in grouped["complexity"]] == ["c"]
    assert [i.key for i in grouped["performance"]] == ["p"]
    assert [i.key for i in grouped["test_coverage"]] == ["t"]
    assert [i.key for i in grouped["style"]] == ["st"]


# --- master scan ------------------------------------------------------------


async def test_scan_full_success(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_exec(*command, **kwargs):
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    _patch_http(
        monkeypatch,
        {
            ("POST", "/api/projects/create"): lambda r: httpx.Response(200),
            ("POST", "/api/projects/delete"): lambda r: httpx.Response(204),
            ("GET", "/api/ce/activity"): lambda r: _ce("SUCCESS"),
            (
                "GET",
                "/api/issues/search",
            ): lambda r: httpx.Response(200, json={"total": 0, "issues": []}),
        },
    )
    grouped = await scan("proj-key", [{"filename": "a.py", "content": "x"}], "python")
    assert set(grouped) == set(AGENT_BUCKETS)


async def test_scan_propagates_sonarqube_error_and_still_deletes(monkeypatch):
    _patch_settings(monkeypatch)
    deleted = []

    def delete_ok(request):
        deleted.append(request.url.params.get("project"))
        return httpx.Response(204)

    _patch_http(
        monkeypatch,
        {
            ("POST", "/api/projects/create"): lambda r: httpx.Response(
                404, text="cannot create"
            ),
            ("POST", "/api/projects/delete"): delete_ok,
        },
    )
    with pytest.raises(SonarQubeError, match="Failed to create"):
        await scan("proj-key", [], "python")
    assert deleted == ["proj-key"]  # finally always cleans up


async def test_scan_wraps_transport_errors(monkeypatch):
    _patch_settings(monkeypatch)

    def create_down(request):
        raise httpx.ConnectError("sonar down")

    _patch_http(
        monkeypatch,
        {
            ("POST", "/api/projects/create"): create_down,
            ("POST", "/api/projects/delete"): lambda r: httpx.Response(204),
        },
    )
    with pytest.raises(SonarQubeError, match="SonarQube API unreachable"):
        await scan("proj-key", [], "python")


async def test_scan_wraps_io_errors(monkeypatch):
    _patch_settings(monkeypatch)
    _patch_http(
        monkeypatch,
        {
            ("POST", "/api/projects/create"): lambda r: httpx.Response(200),
            ("POST", "/api/projects/delete"): lambda r: httpx.Response(204),
        },
    )
    # filename "." resolves to the temp root itself → IsADirectoryError
    # (an OSError subclass) raised while writing.
    with pytest.raises(SonarQubeError, match="scan I/O failure"):
        await scan("proj-key", [{"filename": ".", "content": "x"}], "python")
