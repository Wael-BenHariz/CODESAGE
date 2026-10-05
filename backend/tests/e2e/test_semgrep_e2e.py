"""E2E scan tests against the DEPLOYED semgrep-service (k8s).

Opt-in: every test is skipped unless ``SEMGREP_E2E_URL`` points at a
reachable service — ``scripts/smoke_semgrep.sh`` sets it after starting
``kubectl -n codesage port-forward svc/semgrep-service``. Unlike the
rest of the suite these tests need no local Postgres/Redis: the
module-level ``_clean_state`` shadow below replaces the parent
conftest's DB cleaner for this file.

What is REAL here: the cluster service, the tar.gz upload round trip,
semgrep itself with the baked OSS rule packs, normalization,
cross-tool merge, snippet enrichment, and the client's failure paths
(real sockets — no mock transports). What is STUBBED in the full
pipeline test: SonarQube only — the scanner binary exists solely inside
the worker image, so sonar's side is a recording stub with an
artificial delay. Parallelism is therefore proven by the two scans'
OVERLAPPING intervals plus elapsed < sum(durations), not by a
wall-clock guess.

Budget: two real scans at ~40 s each (rule-pack load dominates, cold
and warm alike) + two fast failure paths — the file runs in ~90 s.
"""

import asyncio
import os
import time
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.services import static_analysis
from app.services.normalizers import enrich_snippets, normalize_semgrep
from app.services.semgrep import SemgrepClient, SemgrepError, build_scan_archive
from app.services.sonarqube import SonarIssue

E2E_URL = os.environ.get("SEMGREP_E2E_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(
    not E2E_URL,
    reason="SEMGREP_E2E_URL not set — run scripts/smoke_semgrep.sh",
)


@pytest.fixture(autouse=True)
def _clean_state():
    """Shadow of the parent conftest's DB/Redis cleaner — a no-op here.

    ``run_static_analysis`` and ``SemgrepClient`` never touch the
    database, so truncating Postgres/flushing Redis per test is pure
    overhead — and would make the smoke script require docker-compose
    up. Deliberately defined in THIS MODULE rather than a nested
    ``tests/e2e/conftest.py``: sibling test modules do
    ``from conftest import ...`` and a second conftest.py on the import
    path hijacks that module name (they'd resolve to this directory's
    conftest instead of ``tests/conftest.py``).
    """
    yield


# The eval lands on line 5 and pickle.loads on line 6; a clean file
# next to it proves findings don't bleed across the workspace.
VULN_SOURCE = (
    "import os\n"
    "import pickle\n"
    "\n"
    "def run(user_input, blob):\n"
    "    eval(user_input)\n"
    "    pickle.loads(blob)\n"
    "    return os.getcwd()\n"
)
FILES = [
    {"filename": "src/app.py", "content": VULN_SOURCE},
    {"filename": "src/util.py", "content": "def add(a, b):\n    return a + b\n"},
]
FILENAMES = [file["filename"] for file in FILES]

# Overlaps semgrep's eval finding exactly (same file, line, CWE-95) so
# the merge must fold them into one row.
SONAR_ISSUE = SonarIssue(
    key="E2E1",
    rule="python:S4502",
    severity="MAJOR",
    type="VULNERABILITY",
    component="src/app.py",
    line=5,
    message="Possible code injection.",
    effort="5min",
    tags=["external/cwe/cwe-95", "owasp2021-a03-injection"],
)


async def _run_static_analysis():
    return await static_analysis.run_static_analysis(
        review_id="e2e-review",
        project_key="codesage-review-e2e",
        files=FILES,
        language="python",
    )


@pytest.fixture
def sonar_stub(monkeypatch):
    """Recording SonarQube stub: canned finding, optional delay, timestamps."""
    state = SimpleNamespace(calls=0, delay=0.0, intervals={})

    async def scan(**kwargs):
        state.calls += 1
        start = time.monotonic()
        if state.delay:
            await asyncio.sleep(state.delay)
        state.intervals["sonarqube"] = (start, time.monotonic())
        return {"security": [SONAR_ISSUE]}

    monkeypatch.setattr(
        static_analysis, "sonarqube_service", SimpleNamespace(scan=scan)
    )
    return state


# --- connectivity ------------------------------------------------------------


async def test_service_reports_ready():
    """healthz (liveness) and readyz (binary + baked rule packs) over the
    port-forward — the same endpoints the worker's client polls."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        health = await client.get(f"{E2E_URL}/healthz")
        ready = await client.get(f"{E2E_URL}/readyz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ready"
    assert body["rules"]  # rules dir reported, not a 503


# --- real scan through the production client ---------------------------------


async def test_scan_output_lands_on_the_workspace(tmp_path):
    """Upload the fixture workspace, scan it live, normalize the result.

    Guards the two dialect gaps seen against the deployed service: the
    reported paths are absolute inside its per-request temp dir and the
    check_id prefix mirrors the full ``--config`` path
    (``opt.semgrep-rules.…``). Both must be reconciled away here.
    """
    archive = tmp_path / "scan.tar.gz"
    assert build_scan_archive(FILES, archive) == len(FILES)

    report = await SemgrepClient(base_url=E2E_URL).async_scan(archive)
    assert report["results"], "expected live findings (eval + pickle fixture)"

    findings = normalize_semgrep(report, files=FILES)
    assert findings
    # Paths land on the uploaded names — never the service's /tmp tree.
    assert all(f.file_path in FILENAMES for f in findings)
    assert any(f.file_path == "src/app.py" for f in findings)
    # Clean file stays clean: findings only where they were found.
    assert not any(f.file_path == "src/util.py" for f in findings)
    # Config-path prefix stripped to the canonical namespace.
    assert all(not f.rule_id.startswith(("opt.", "semgrep-rules.")) for f in findings)
    rule_ids = {f.rule_id for f in findings}
    assert any("eval-detected" in rule_id for rule_id in rule_ids)
    assert any("avoid-pickle" in rule_id for rule_id in rule_ids)
    # WARNING is semgrep's strongest on these rules -> medium.
    assert all(f.severity in {"medium", "high"} for f in findings)
    # Snippet enrichment keys on the reconciled path: numbered window
    # rewritten from the workspace (single-line semgrep snippets are
    # replaced by the ±10-line excerpt).
    assert enrich_snippets(findings, FILES) >= 1
    assert any((f.snippet or "").startswith("1: ") for f in findings)


# --- full pipeline: parallel execution + merge --------------------------------


async def test_full_pipeline_runs_tools_in_parallel_and_merges(sonar_stub, monkeypatch):
    """``run_static_analysis`` end to end against the live service.

    Semgrep runs for real (~40 s); SonarQube is a 3 s recording stub.
    Parallelism is asserted twice: the intervals OVERLAP (sequential
    execution would start semgrep only after sonar's interval closed)
    and the total elapsed time is below the SUM of the two durations.
    """
    sonar_stub.delay = 3.0
    monkeypatch.setattr(settings, "SEMGREP_SERVICE_URL", E2E_URL)
    intervals = sonar_stub.intervals

    class LiveSemgrepClient(SemgrepClient):
        """Production client with start/end timestamps recorded."""

        async def async_scan(self, *args, **kwargs):
            start = time.monotonic()
            try:
                return await super().async_scan(*args, **kwargs)
            finally:
                intervals["semgrep"] = (start, time.monotonic())

    monkeypatch.setattr(static_analysis, "SemgrepClient", LiveSemgrepClient)

    started = time.monotonic()
    result = await _run_static_analysis()
    elapsed = time.monotonic() - started

    # Both tools ran against their real/stubbed endpoints, none failed.
    assert result.report.tools_run == ["sonarqube", "semgrep"]
    assert result.report.tools_failed == []
    assert result.sonar_error is None and result.semgrep_error is None
    assert sonar_stub.calls == 1

    # --- parallel timing evidence (overlapping intervals) ---------------
    sem_start, sem_end = intervals["semgrep"]
    son_start, son_end = intervals["sonarqube"]
    assert sem_start < son_end, (
        "semgrep started only after sonar finished — not parallel "
        f"(semgrep start +{sem_start - son_start:.2f}s, "
        f"sonar end +{son_end - son_start:.2f}s)"
    )
    sem_duration = sem_end - sem_start
    sonar_duration = son_end - son_start
    assert elapsed < sem_duration + sonar_duration, (
        f"sequential-shaped timing: elapsed {elapsed:.2f}s >= "
        f"sum of scans {sem_duration + sonar_duration:.2f}s"
    )

    # --- merged, reconciled, enriched report -----------------------------
    findings = result.report.findings
    merged = [f for f in findings if f.also_detected_by]
    assert len(merged) == 1
    survivor = merged[0]
    assert survivor.tool == "sonarqube"  # primary tool keeps its slot
    assert survivor.file_path == "src/app.py"
    assert survivor.line_start == 5
    assert "CWE-95" in survivor.cwe
    assert survivor.also_detected_by == ["semgrep"]
    # semgrep's second finding (pickle / CWE-502, line 6) stays separate.
    assert any(f.tool == "semgrep" and "CWE-502" in f.cwe for f in findings)
    # Every finding sits on a workspace filename (path reconciliation).
    assert all(f.file_path in FILENAMES for f in findings)
    # Every finding carries a numbered workspace excerpt for the agents.
    assert all(f.snippet and "\n" in f.snippet for f in findings)


# --- failure modes ------------------------------------------------------------


async def test_unreachable_service_fails_softly(sonar_stub, monkeypatch):
    """A dead endpoint must isolate semgrep, not sink the review —
    exercised over a real socket (closed local port), no mock transport."""
    monkeypatch.setattr(settings, "SEMGREP_SERVICE_URL", "http://127.0.0.1:9")

    result = await _run_static_analysis()

    assert result.report.tools_run == ["sonarqube"]
    assert [f.tool for f in result.report.tools_failed] == ["semgrep"]
    assert result.semgrep_error.startswith("Semgrep scan failed")
    assert "unreachable" in result.semgrep_error
    assert result.sonar_error is None
    assert result.both_failed is False
    assert len(result.report.findings) == 1  # sonar's finding survives
    assert result.report.findings[0].tool == "sonarqube"


async def test_malformed_upload_is_rejected_fast(tmp_path):
    """Garbage bytes reach the service and come back as an immediate
    400 (4xx is never retried) wrapped in SemgrepError."""
    junk = tmp_path / "not-an-archive.tar.gz"
    junk.write_bytes(b"this is not a tarball")
    client = SemgrepClient(base_url=E2E_URL, max_retries=0)

    with pytest.raises(SemgrepError) as excinfo:
        await client.async_scan(junk, languages=["python"])

    message = str(excinfo.value)
    assert "HTTP 400" in message
    assert "invalid tar.gz" in message
