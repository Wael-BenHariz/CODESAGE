"""SemgrepClient: upload contract, retries/backoff, and error taxonomy.

All tests run against ``httpx.MockTransport`` — no network, no running
service. Retry behaviour is asserted by counting handler invocations.
"""

import json
import tarfile

import httpx
import pytest

from app.config import settings
from app.services.semgrep import (
    SemgrepClient,
    SemgrepError,
    build_scan_archive,
)

_REPORT = {"version": "1.178.0", "results": [], "errors": []}


def _client(handler, **kwargs) -> tuple[SemgrepClient, list]:
    """Client bound to a MockTransport handler + the request log."""
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    kwargs.setdefault("backoff_seconds", 0.0)
    client = SemgrepClient(
        transport=httpx.MockTransport(wrapped),
        **kwargs,
    )
    return client, calls


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_REPORT)


def _archive(tmp_path, content: bytes = b"not-really-gzip-but-nonempty"):
    path = tmp_path / "sonar_files.tar.gz"
    path.write_bytes(content)
    return path


# --- happy path -------------------------------------------------------------


async def test_scan_returns_parsed_report_and_posts_multipart(tmp_path):
    client, calls = _client(_ok)
    report = await client.async_scan(_archive(tmp_path))

    assert report == _REPORT
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    assert request.url.path == "/scan"
    assert request.url.params["timeout"] == str(settings.SEMGREP_TIMEOUT_SECONDS)
    assert "multipart/form-data" in request.headers["content-type"]
    assert b"scan.tar.gz" in request.content


async def test_scan_passes_languages_and_timeout_override(tmp_path):
    client, calls = _client(_ok)
    await client.async_scan(
        _archive(tmp_path), languages=["python", "java"], timeout=30
    )
    params = calls[0].url.params
    assert params["languages"] == "python,java"
    assert params["timeout"] == "30"


def test_default_base_url_comes_from_settings_and_is_normalized():
    assert SemgrepClient().base_url == settings.SEMGREP_SERVICE_URL
    assert SemgrepClient(base_url="http://svc:8080/").base_url == ("http://svc:8080")


# --- retries / backoff ------------------------------------------------------


async def test_retryable_503_then_success(tmp_path):
    attempts = 0

    def flaky(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"detail": "starting"})
        return httpx.Response(200, json=_REPORT)

    client, _ = _client(flaky, max_retries=2)
    report = await client.async_scan(_archive(tmp_path))
    assert report == _REPORT
    assert attempts == 2


async def test_connect_errors_exhaust_retries_then_raise(tmp_path):
    attempts = 0

    def down(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection refused", request=request)

    client, _ = _client(down, max_retries=2)
    with pytest.raises(SemgrepError, match="unreachable after 3 attempt"):
        await client.async_scan(_archive(tmp_path))
    assert attempts == 3


async def test_504_is_retried_and_raises_when_exhausted(tmp_path):
    attempts = 0

    def always_timeout(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(504, json={"detail": "scan timed out"})

    client, _ = _client(always_timeout, max_retries=1)
    with pytest.raises(SemgrepError, match="HTTP 504: scan timed out"):
        await client.async_scan(_archive(tmp_path))
    assert attempts == 2


# --- non-retryable failures -------------------------------------------------


async def test_4xx_fails_immediately_with_service_detail(tmp_path):
    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "unsupported language 'cobol'"})

    client, calls = _client(rejected, max_retries=5)
    with pytest.raises(SemgrepError, match="unsupported language 'cobol'"):
        await client.async_scan(_archive(tmp_path))
    assert len(calls) == 1  # 4xx never retried


async def test_invalid_json_report_raises(tmp_path):
    client, _ = _client(
        lambda _r: httpx.Response(200, content=b"<html>not json</html>")
    )
    with pytest.raises(SemgrepError, match="invalid JSON"):
        await client.async_scan(_archive(tmp_path))


async def test_json_without_results_list_raises(tmp_path):
    client, _ = _client(lambda _r: httpx.Response(200, json={"foo": 1}))
    with pytest.raises(SemgrepError, match="missing 'results'"):
        await client.async_scan(_archive(tmp_path))


# --- pre-flight guards (transport must not be touched) ----------------------


async def test_empty_archive_rejected_before_upload(tmp_path):
    def must_not_run(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("transport should not be called")

    client, calls = _client(must_not_run)
    with pytest.raises(SemgrepError, match="archive is empty"):
        await client.async_scan(_archive(tmp_path, b""))
    assert calls == []


async def test_oversized_archive_rejected_before_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SEMGREP_MAX_UPLOAD_BYTES", 8)

    def must_not_run(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("transport should not be called")

    client, calls = _client(must_not_run)
    with pytest.raises(SemgrepError, match="service accepts at most 8"):
        await client.async_scan(_archive(tmp_path, b"0123456789"))
    assert calls == []


# --- health -----------------------------------------------------------------


async def test_health_reports_ready():
    client, calls = _client(_ok)
    assert await client.health() is True
    assert calls[0].url.path == "/readyz"


async def test_health_false_when_not_ready_or_down():
    not_ready, _ = _client(lambda _r: httpx.Response(503))
    assert await not_ready.health() is False

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    unreachable, _ = _client(down)
    assert await unreachable.health() is False


# --- report shape guard -----------------------------------------------------


def test_report_validation_rejects_non_dict():
    with pytest.raises(SemgrepError, match="not a semgrep report"):
        SemgrepClient._parse_report(httpx.Response(200, json=[{"results": []}]))
    # A dict whose "results" is the wrong type is also rejected.
    with pytest.raises(SemgrepError, match="missing 'results'"):
        SemgrepClient._parse_report(httpx.Response(200, json={"results": "nope"}))


def test_detail_falls_back_to_text_for_non_json_errors():
    response = httpx.Response(500, content=b"boom")
    assert SemgrepClient._detail(response) == "boom"
    assert SemgrepClient._detail(httpx.Response(400, json={"detail": "why"})) == "why"
    # JSON without a known detail key degrades to the body text.
    assert json.loads(SemgrepClient._detail(httpx.Response(400, json={"x": 1}))) == {
        "x": 1
    }


# --- build_scan_archive -----------------------------------------------------


def test_build_scan_archive_packs_files(tmp_path):
    dest = tmp_path / "scan.tar.gz"
    written = build_scan_archive(
        [
            {"filename": "src/a.py", "content": "x = 1\n"},
            {"filename": "b.py", "content": "y = 2"},
            {"filename": "", "content": "skip"},  # no name
            {"filename": "empty.py", "content": ""},  # no content
            {  # path traversal -> rejected
                "filename": "evil/../../etc/passwd",
                "content": "z",
            },
            {  # absolute path -> leading slash stripped, kept
                "filename": "/abs/path.py",
                "content": "w",
            },
        ],
        dest,
    )

    assert written == 3
    with tarfile.open(dest, "r:gz") as tar:
        names = sorted(tar.getnames())
        assert names == ["abs/path.py", "b.py", "src/a.py"]
        payload = tar.extractfile("src/a.py").read()
    assert payload == b"x = 1\n"


def test_build_scan_archive_accepts_bytes(tmp_path):
    dest = tmp_path / "scan.tar.gz"
    written = build_scan_archive(
        [{"filename": "img.bin", "content": b"\x00\x01"}], dest
    )
    assert written == 1
    with tarfile.open(dest, "r:gz") as tar:
        assert tar.extractfile("img.bin").read() == b"\x00\x01"


def test_build_scan_archive_zero_when_nothing_scannable(tmp_path):
    dest = tmp_path / "scan.tar.gz"
    written = build_scan_archive([{"filename": "../escape.py", "content": "x"}], dest)
    assert written == 0
    # Archive exists but is empty — callers check the count, not the file.
    with tarfile.open(dest, "r:gz") as tar:
        assert tar.getnames() == []
