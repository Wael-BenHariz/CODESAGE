"""SonarQube client: project lifecycle, scanner execution, issue fetching.

SonarQube Community Edition allows only one branch per project, so every
review gets a unique throwaway project (``codesage-review-<review[:8]>``)
that is always deleted afterwards — success or failure.

Design constraints (see implementation brief):
- All API calls go through ``httpx.AsyncClient``.
- The scanner CLI runs via ``asyncio.create_subprocess_exec`` — never
  ``subprocess.run``, which would block the worker event loop.
- Any failure raises ``SonarQubeError``/``SonarQubeTimeoutError`` so the
  worker can fall back to empty issue groups instead of failing the review.
"""

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Issue buckets keyed by specialist agent domain. Lookup order matters:
# an issue lands in the FIRST bucket whose predicate matches (A2.8).
AGENT_BUCKETS = ("security", "complexity", "performance", "test_coverage", "style")

SECURITY_TAGS = {"sql", "injection", "xss", "crypto", "auth", "owasp"}
COMPLEXITY_TAGS = {"brain-overload", "complex", "design"}
COMPLEXITY_RULES = {
    "java:S3776",
    "java:S1541",
    "java:S138",
    "python:FunctionComplexity",
    "python:S3776",
}
PERFORMANCE_TAGS = {"performance", "memory", "cpu", "sql"}
TEST_TAGS = {"tests", "unused", "coverage"}

ISSUES_PAGE_SIZE = 500


class SonarQubeError(Exception):
    """Any SonarQube API or scanner failure."""


class SonarQubeTimeoutError(SonarQubeError):
    """Analysis did not finish within SONARQUBE_ANALYSIS_TIMEOUT."""


@dataclass
class SonarIssue:
    key: str
    rule: str  # e.g. "java:S2077"
    severity: str  # BLOCKER | CRITICAL | MAJOR | MINOR | INFO
    type: str  # BUG | VULNERABILITY | CODE_SMELL | SECURITY_HOTSPOT
    component: str  # file path (project key prefix stripped)
    line: int | None
    message: str
    effort: str | None
    tags: list[str] = field(default_factory=list)


def _auth_headers() -> dict[str, str]:
    if not settings.SONARQUBE_TOKEN:
        raise SonarQubeError("SONARQUBE_TOKEN is not configured")
    return {"Authorization": f"Bearer {settings.SONARQUBE_TOKEN}"}


# ---------------------------------------------------------------------------
# Project lifecycle
# ---------------------------------------------------------------------------


async def create_project(project_key: str, project_name: str) -> None:
    """Create the analysis project. 400 "already exists" is tolerated."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.SONARQUBE_URL}/api/projects/create",
            params={"project": project_key, "name": project_name},
            headers=_auth_headers(),
        )

    if response.status_code in (200, 201):
        return
    if response.status_code == 400 and "already exists" in response.text.lower():
        logger.info("SonarQube project %s already exists", project_key)
        return
    raise SonarQubeError(
        f"Failed to create SonarQube project {project_key}: "
        f"HTTP {response.status_code} {response.text[:300]}"
    )


async def delete_project(project_key: str) -> None:
    """Delete the analysis project. Cleanup is best-effort: never raise."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.SONARQUBE_URL}/api/projects/delete",
                params={"project": project_key},
                headers=_auth_headers(),
            )
        if response.status_code not in (200, 204):
            logger.warning(
                "SonarQube project delete for %s returned HTTP %s: %s",
                project_key,
                response.status_code,
                response.text[:300],
            )
    except Exception as exc:  # noqa: BLE001 — cleanup must never raise
        logger.warning(
            "SonarQube project delete for %s failed (best-effort): %r",
            project_key,
            exc,
        )


# ---------------------------------------------------------------------------
# Temp workspace
# ---------------------------------------------------------------------------


def write_files_to_temp_dir(files: list[dict], temp_dir: str) -> None:
    """Write ``[{"filename", "content"}]`` entries under ``temp_dir``.

    Relative paths from GitHub (e.g. ``src/main/java/UserService.java``) are
    preserved exactly so rules report realistic component paths. Empty
    contents are skipped. Path traversal outside ``temp_dir`` is rejected.
    """
    root = Path(temp_dir).resolve()

    for file in files:
        filename = str(file.get("filename") or "").strip()
        content = file.get("content")
        if not filename or not content:
            continue

        target = (root / filename).resolve()
        if not str(target).startswith(str(root) + os.sep) and target != root:
            logger.warning("Skipping file with unsafe path: %s", filename)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


async def run_scanner(project_key: str, temp_dir: str, language: str) -> None:
    """Run ``sonar-scanner`` against ``temp_dir`` (async, non-blocking)."""
    logger.info(
        "Running sonar-scanner for project %s (language=%s)",
        project_key,
        language,
    )
    command = [
        "sonar-scanner",
        f"-Dsonar.projectKey={project_key}",
        f"-Dsonar.projectName={project_key}",
        "-Dsonar.sources=.",
        f"-Dsonar.host.url={settings.SONARQUBE_URL}",
        f"-Dsonar.token={settings.SONARQUBE_TOKEN}",
        f"-Dsonar.working.directory={temp_dir}/.scannerwork",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=temp_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise SonarQubeError(f"failed to launch sonar-scanner: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=settings.SONARQUBE_ANALYSIS_TIMEOUT,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise SonarQubeTimeoutError(
            f"sonar-scanner timed out after "
            f"{settings.SONARQUBE_ANALYSIS_TIMEOUT}s for {project_key}"
        ) from exc

    if process.returncode != 0:
        stderr_tail = "\n".join(
            (stderr or b"").decode("utf-8", errors="replace").splitlines()[-20:]
        )
        stdout_tail = "\n".join(
            (stdout or b"").decode("utf-8", errors="replace").splitlines()[-20:]
        )
        raise SonarQubeError(
            f"sonar-scanner exited with code {process.returncode} "
            f"for project {project_key}.\n"
            f"--- stderr (last 20 lines) ---\n{stderr_tail}\n"
            f"--- stdout (last 20 lines) ---\n{stdout_tail}"
        )


# ---------------------------------------------------------------------------
# Analysis polling
# ---------------------------------------------------------------------------


async def wait_for_analysis(project_key: str) -> str:
    """Poll the Compute Engine until the analysis task completes.

    Returns the completed task id on SUCCESS; raises SonarQubeError on
    FAILED/CANCELLED and SonarQubeTimeoutError when no terminal task appears
    within ``SONARQUBE_ANALYSIS_TIMEOUT`` seconds.
    """
    deadline = time.monotonic() + settings.SONARQUBE_ANALYSIS_TIMEOUT

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            response = await client.get(
                f"{settings.SONARQUBE_URL}/api/ce/activity",
                params={
                    "component": project_key,
                    # API spelling is CANCELED (one L); CANCELLED is rejected.
                    "status": "SUCCESS,FAILED,CANCELED",
                },
                headers=_auth_headers(),
            )
            if response.status_code != 200:
                raise SonarQubeError(
                    f"Failed to poll analysis for {project_key}: "
                    f"HTTP {response.status_code} {response.text[:300]}"
                )

            tasks = response.json().get("tasks") or []
            if tasks:
                task = tasks[0]
                status = str(task.get("status", "")).upper()
                task_id = str(task.get("id") or "")
                if status == "SUCCESS":
                    return task_id
                if status in ("FAILED", "CANCELLED", "CANCELED"):
                    raise SonarQubeError(
                        f"Analysis failed for project {project_key} "
                        f"(status={status}, task={task_id})"
                    )

            if time.monotonic() >= deadline:
                raise SonarQubeTimeoutError(
                    f"Analysis for {project_key} did not complete within "
                    f"{settings.SONARQUBE_ANALYSIS_TIMEOUT}s"
                )
            await asyncio.sleep(settings.SONARQUBE_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


async def get_issues(project_key: str) -> list[SonarIssue]:
    """Fetch all unresolved issues for the project (paginated, 500/page)."""
    issues: list[SonarIssue] = []
    page = 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            response = await client.get(
                f"{settings.SONARQUBE_URL}/api/issues/search",
                params={
                    "componentKeys": project_key,
                    "resolved": "false",
                    "ps": ISSUES_PAGE_SIZE,
                    "p": page,
                },
                headers=_auth_headers(),
            )
            if response.status_code != 200:
                raise SonarQubeError(
                    f"Failed to fetch issues for {project_key}: "
                    f"HTTP {response.status_code} {response.text[:300]}"
                )

            payload = response.json()
            total = int(payload.get("total") or 0)

            for raw in payload.get("issues") or []:
                component = str(raw.get("component") or "")
                # component comes back as "<projectKey>:<path>" — keep the path.
                if ":" in component:
                    component = component.split(":", 1)[1]
                issues.append(
                    SonarIssue(
                        key=str(raw.get("key") or ""),
                        rule=str(raw.get("rule") or ""),
                        severity=str(raw.get("severity") or "INFO").upper(),
                        type=str(raw.get("type") or "").upper(),
                        component=component,
                        line=raw.get("line"),
                        message=str(raw.get("message") or ""),
                        effort=raw.get("effort"),
                        tags=[str(t) for t in (raw.get("tags") or [])],
                    )
                )

            if page * ISSUES_PAGE_SIZE >= total:
                break
            page += 1

    return issues


def group_issues_by_agent(issues: list[SonarIssue]) -> dict[str, list[SonarIssue]]:
    """Bucket issues per specialist agent domain — first matching bucket wins.

    Priority: security -> complexity -> performance -> test_coverage -> style.
    Returns a dict containing every bucket key (possibly empty) so callers
    can use ``groups.get(domain, [])`` safely.
    """
    grouped: dict[str, list[SonarIssue]] = {bucket: [] for bucket in AGENT_BUCKETS}

    for issue in issues:
        grouped[_classify_issue(issue)].append(issue)

    return grouped


def _classify_issue(issue: SonarIssue) -> str:
    tags = {tag.lower() for tag in issue.tags}

    # 1. security — vulnerabilities, hotspots, and security-tagged issues
    if issue.type in ("VULNERABILITY", "SECURITY_HOTSPOT") or (tags & SECURITY_TAGS):
        return "security"

    # 2. complexity — complexity smells (by tag or known rule keys)
    if issue.type == "CODE_SMELL" and (
        tags & COMPLEXITY_TAGS or issue.rule in COMPLEXITY_RULES
    ):
        return "complexity"

    # 3. performance — perf/memory/cpu/sql tags, but never a vulnerability
    if issue.type != "VULNERABILITY" and (tags & PERFORMANCE_TAGS):
        return "performance"

    # 4. test_coverage — test-related smells
    if issue.type == "CODE_SMELL" and (tags & TEST_TAGS):
        return "test_coverage"

    # 5. style — everything else (catch-all)
    return "style"


# ---------------------------------------------------------------------------
# Master scan
# ---------------------------------------------------------------------------


async def scan(
    project_key: str,
    files: list[dict],
    language: str,
) -> dict[str, list[SonarIssue]]:
    """Create a temp project, analyze the given files, return grouped issues.

    The project is always deleted afterwards (best-effort), success or fail.
    Raises SonarQubeError / SonarQubeTimeoutError on any failure — callers
    fall back to empty groups.
    """
    with tempfile.TemporaryDirectory(prefix="sonarqube-scan-") as temp_dir:
        try:
            await create_project(project_key, project_key)
            write_files_to_temp_dir(files, temp_dir)
            await run_scanner(project_key, temp_dir, language)
            await wait_for_analysis(project_key)
            issues = await get_issues(project_key)
            grouped = group_issues_by_agent(issues)
            logger.info(
                "SonarQube scan complete for %s: %d issues",
                project_key,
                len(issues),
            )
            return grouped
        except SonarQubeError:
            raise
        except httpx.HTTPError as exc:
            # Unreachable/timeout SonarQube must surface as SonarQubeError so
            # the worker falls back to empty groups instead of failing the
            # review (hard constraint 3).
            raise SonarQubeError(
                f"SonarQube API unreachable at {settings.SONARQUBE_URL}: {exc}"
            ) from exc
        except OSError as exc:
            raise SonarQubeError(f"SonarQube scan I/O failure: {exc}") from exc
        finally:
            await delete_project(project_key)


class SonarQubeService:
    """Facade so callers can ``sonarqube_service.scan(...)`` (A7 import)."""

    create_project = staticmethod(create_project)
    delete_project = staticmethod(delete_project)
    write_files_to_temp_dir = staticmethod(write_files_to_temp_dir)
    run_scanner = staticmethod(run_scanner)
    wait_for_analysis = staticmethod(wait_for_analysis)
    get_issues = staticmethod(get_issues)
    group_issues_by_agent = staticmethod(group_issues_by_agent)
    scan = staticmethod(scan)


sonarqube_service = SonarQubeService()
