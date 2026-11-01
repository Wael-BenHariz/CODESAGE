"""Opt-in black-box Semgrep benchmark against the configured live service."""

import io
import os
import tarfile

import httpx
import pytest


@pytest.mark.e2e
@pytest.mark.live
def test_semgrep_detects_controlled_python_defect(tmp_path):
    base_url = os.getenv("SEMGREP_LIVE_URL")
    if not base_url:
        pytest.skip("Set SEMGREP_LIVE_URL to the live semgrep-service endpoint")
    source = b"import subprocess\ndef run(value):\n    return subprocess.check_output(value, shell=True)\n"
    archive_path = tmp_path / "benchmark.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("vulnerable.py")
        info.size = len(source)
        archive.addfile(info, io.BytesIO(source))
    with httpx.Client(timeout=180) as client:
        ready = client.get(f"{base_url.rstrip('/')}/readyz")
        assert ready.status_code == 200
        response = client.post(
            f"{base_url.rstrip('/')}/scan",
            params={"languages": "python"},
            files={
                "file": (
                    "benchmark.tar.gz",
                    archive_path.read_bytes(),
                    "application/gzip",
                )
            },
        )
    assert response.status_code == 200
    report = response.json()
    assert any(
        "shell" in str(result).lower() or "subprocess" in str(result).lower()
        for result in report.get("results", [])
    )
