"""API contract tests — the semgrep subprocess is stubbed here.

Covers: health/ready endpoints, multipart scan happy path, parameter
handling (languages/timeout), size limits, archive rejection, HTTP error
mapping (504/502), and the concurrency semaphore.
"""

import asyncio
import io
import sys
import tarfile

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, scanner
from app.main import create_app

GZIP = "application/gzip"


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _dir_tar_bytes(name: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=name)
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
    return buf.getvalue()


@pytest.fixture
def client():
    return TestClient(create_app())


def _stub_scan(monkeypatch, result=None, error=None) -> dict:
    """Replace scanner.run_semgrep with a recording stub."""
    calls: dict = {}

    async def fake(target_dir, *, timeout, languages=None):
        calls["timeout"] = timeout
        calls["languages"] = languages
        calls["files"] = sorted(
            str(p.relative_to(target_dir)) for p in target_dir.rglob("*") if p.is_file()
        )
        if error is not None:
            raise error
        return result if result is not None else {"results": []}

    monkeypatch.setattr("app.scanner.run_semgrep", fake)
    return calls


def _post_scan(client, files=None, **params):
    return client.post(
        "/scan",
        params=params or None,
        files={
            "file": (
                "upload.tar.gz",
                files if files is not None else _tar_bytes({"a.py": b"x=1\n"}),
                GZIP,
            )
        },
    )


# --- health / readiness -----------------------------------------------------


def test_healthz_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ok_when_binary_and_rules_present(tmp_path, monkeypatch):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "audit.yml").write_text("rules: []\n")
    monkeypatch.setattr(config, "SEMGREP_RULES_DIR", str(rules))
    monkeypatch.setattr(config, "SEMGREP_BINARY", sys.executable)
    response = TestClient(create_app()).get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_503_when_rules_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEMGREP_RULES_DIR", str(tmp_path / "absent"))
    monkeypatch.setattr(config, "SEMGREP_BINARY", sys.executable)
    response = TestClient(create_app()).get("/readyz")
    assert response.status_code == 503
    assert "rules dir missing" in response.json()["detail"]


def test_readyz_503_when_rules_dir_empty(tmp_path, monkeypatch):
    rules = tmp_path / "rules"
    rules.mkdir()
    monkeypatch.setattr(config, "SEMGREP_RULES_DIR", str(rules))
    monkeypatch.setattr(config, "SEMGREP_BINARY", sys.executable)
    response = TestClient(create_app()).get("/readyz")
    assert response.status_code == 503
    assert "no rule files" in response.json()["detail"]


def test_readyz_503_when_binary_missing(tmp_path, monkeypatch):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "audit.yml").write_text("rules: []\n")
    monkeypatch.setattr(config, "SEMGREP_RULES_DIR", str(rules))
    monkeypatch.setattr(config, "SEMGREP_BINARY", "/nonexistent/definitely-not-semgrep")
    response = TestClient(create_app()).get("/readyz")
    assert response.status_code == 503
    assert "binary not found" in response.json()["detail"]


# --- scan happy path & params ----------------------------------------------


def test_scan_returns_semgrep_json_verbatim(client, monkeypatch):
    canned = {
        "results": [
            {
                "check_id": "python.lang.security.audit.eval-used",
                "path": "a.py",
                "start": {"line": 1, "col": 1},
            }
        ],
        "errors": [],
        "version": "1.178.0",
    }
    calls = _stub_scan(monkeypatch, result=canned)
    response = _post_scan(client, files=_tar_bytes({"a.py": b"x=1\n"}))
    assert response.status_code == 200
    assert response.json() == canned
    assert calls["files"] == ["a.py"]
    assert calls["languages"] is None
    assert calls["timeout"] == config.SEMGREP_TIMEOUT_SECONDS


def test_scan_passes_timeout_and_languages(client, monkeypatch):
    calls = _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, timeout=30, languages="python, java")
    assert response.status_code == 200
    assert calls["timeout"] == 30
    assert calls["languages"] == ["python", "java"]


def test_scan_clamps_timeout_to_max(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_SCAN_TIMEOUT_SECONDS", 100)
    calls = _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, timeout=99999)
    assert response.status_code == 200
    assert calls["timeout"] == 100


def test_scan_rejects_non_positive_timeout(client, monkeypatch):
    _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, timeout=0)
    assert response.status_code == 422


def test_scan_rejects_unknown_language(client, monkeypatch):
    _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, languages="cobol")
    assert response.status_code == 422
    assert "unsupported language" in response.json()["detail"]


# --- error mapping ----------------------------------------------------------


def test_scan_timeout_maps_to_504(client, monkeypatch):
    _stub_scan(monkeypatch, error=scanner.ScanTimeout("too slow"))
    response = _post_scan(client)
    assert response.status_code == 504
    assert "too slow" in response.json()["detail"]


def test_scan_failure_maps_to_502(client, monkeypatch):
    _stub_scan(monkeypatch, error=scanner.ScanError("boom"))
    response = _post_scan(client)
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


# --- upload / archive guards ------------------------------------------------


def test_scan_rejects_oversized_upload(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 64)
    _stub_scan(monkeypatch, result={"results": []})
    big = _tar_bytes({"big.py": b"x" * 5000})
    response = _post_scan(client, files=big)
    assert response.status_code == 413
    assert "exceeds 64 bytes" in response.json()["detail"]


def test_scan_rejects_empty_upload(client, monkeypatch):
    _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, files=b"")
    assert response.status_code == 400
    assert "empty upload" in response.json()["detail"]


def test_scan_rejects_invalid_archive(client, monkeypatch):
    _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, files=b"this is not a tarball")
    assert response.status_code == 400
    assert "invalid tar.gz" in response.json()["detail"]


def test_scan_rejects_traversal_archive(client, monkeypatch):
    _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, files=_tar_bytes({"../evil.py": b"1"}))
    assert response.status_code == 400
    assert "unsafe path" in response.json()["detail"]


def test_scan_rejects_archive_without_files(client, monkeypatch):
    _stub_scan(monkeypatch, result={"results": []})
    response = _post_scan(client, files=_dir_tar_bytes("subdir"))
    assert response.status_code == 422
    assert "no regular files" in response.json()["detail"]


def test_scan_never_runs_when_archive_rejected(client, monkeypatch):
    calls = _stub_scan(monkeypatch, result={"results": []})
    _post_scan(client, files=b"garbage")
    assert calls == {}


# --- concurrency ------------------------------------------------------------


def test_semaphore_limits_concurrent_scans(monkeypatch):
    monkeypatch.setattr(config, "MAX_CONCURRENT_SCANS", 1)
    active = {"now": 0, "max": 0}

    async def blocking(target_dir, *, timeout, languages=None):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.3)
        active["now"] -= 1
        return {"results": []}

    monkeypatch.setattr("app.scanner.run_semgrep", blocking)
    app = create_app()
    payload = _tar_bytes({"a.py": b"x=1\n"})

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            request = lambda: ac.post(
                "/scan",
                files={"file": ("upload.tar.gz", payload, GZIP)},
            )
            return await asyncio.gather(request(), request())

    response_a, response_b = asyncio.run(main())
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    # With MAX_CONCURRENT_SCANS=1 the scans must not overlap.
    assert active["max"] == 1
