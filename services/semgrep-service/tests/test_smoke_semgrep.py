"""End-to-end smoke against the REAL semgrep binary + baked rules.

Auto-skips when semgrep or the rules directory is unavailable (CI and dev
hosts without the toolchain). Run locally with:

    SEMGREP_RULES_DIR=/path/to/semgrep-rules PATH=/path/to/venv/bin:$PATH \
        python -m pytest tests/test_smoke_semgrep.py -v
"""

import io
import os
import shutil
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "vulnerable"
_RULES_DIR = Path(os.getenv("SEMGREP_RULES_DIR", "/opt/semgrep-rules"))
_BINARY = os.getenv("SEMGREP_BINARY", "semgrep")
_HAS_RULES = _RULES_DIR.is_dir() and (
    any(_RULES_DIR.rglob("*.yml")) or any(_RULES_DIR.rglob("*.yaml"))
)

pytestmark = pytest.mark.skipif(
    not (shutil.which(_BINARY) or Path(_BINARY).is_file()) or not _HAS_RULES,
    reason="requires a semgrep binary on PATH and rules under " "SEMGREP_RULES_DIR",
)


def _fixture_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(_FIXTURE_DIR.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(_FIXTURE_DIR))
    return buf.getvalue()


def test_real_scan_flags_vulnerable_fixture():
    """Real subprocess, real rules: eval()/hardcoded secret must surface."""
    client = TestClient(create_app())
    response = client.post(
        "/scan",
        params={"languages": "python", "timeout": 180},
        files={"file": ("fixture.tar.gz", _fixture_tar(), "application/gzip")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    results = body.get("results") or []
    assert results, f"expected findings from vulnerable fixture: {body}"

    paths = {str(result.get("path") or "") for result in results}
    assert any(path.endswith("app.py") for path in paths), paths

    # Both eval() and pickle.loads() must be caught by the baked packs.
    # (The hardcoded-password line is intentionally not asserted: the
    # packs only carry framework-specific password rules.)
    check_ids = " ".join(
        str(result.get("check_id") or "").lower() for result in results
    )
    assert "eval" in check_ids, check_ids
    assert "pickle" in check_ids, check_ids
