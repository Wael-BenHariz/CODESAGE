"""Client for the standalone Semgrep scan service (stateless upload).

Contract: the worker sends the SAME file workspace SonarQube scans as a
tar.gz to ``POST /scan`` and receives semgrep's JSON report verbatim.
``SEMGREP_ENABLED=false`` skips Semgrep entirely without touching the
SonarQube path.

Unlike the best-effort repo-tenant hook, failures here RAISE
``SemgrepError`` — the caller (worker, Step 5) decides tolerance. The
review pipeline must never fail because of Semgrep.

Timeout chain (one knob, deterministic ordering):

    SEMGREP_TIMEOUT_SECONDS (scan budget, sent as `timeout` param)
      -> service hard kill at budget + KILL_GRACE_SECONDS (30)
      -> this client gives up at budget + CLIENT_GRACE_SECONDS (40)

so the service's clean 504 always arrives before the client aborts.
"""

import asyncio
import io
import logging
import tarfile
from collections.abc import Sequence
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Statuses worth retrying: the service may be rolling or overloaded.
_RETRYABLE_STATUSES = frozenset({502, 503, 504})

# Client HTTP wait = scan budget + this margin; MUST exceed the service's
# KILL_GRACE_SECONDS (30) or the client aborts before the service can
# answer with a proper 504.
CLIENT_GRACE_SECONDS = 40


class SemgrepError(Exception):
    """Service unreachable, erroring, or returning a malformed report."""


class SemgrepClient:
    """Async HTTP client for one semgrep-service base URL."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.SEMGREP_SERVICE_URL).rstrip("/")
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._transport = transport

    async def health(self) -> bool:
        """True when the service reports ready (binary + baked rules)."""
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=5.0
            ) as client:
                response = await client.get(f"{self.base_url}/readyz")
        except httpx.HTTPError as exc:
            logger.debug("semgrep health check failed: %s", exc)
            return False
        return response.status_code == 200

    async def async_scan(
        self,
        archive_path: Path,
        *,
        languages: Sequence[str] | None = None,
        timeout: int | None = None,
    ) -> dict:
        """Upload the tar.gz and return the parsed semgrep JSON report.

        Retries connection errors and 502/503/504 with a short exponential
        backoff; every other failure raises ``SemgrepError`` immediately.
        """
        scan_budget = (
            timeout if timeout is not None else settings.SEMGREP_TIMEOUT_SECONDS
        )
        data = await asyncio.to_thread(archive_path.read_bytes)
        if not data:
            raise SemgrepError(f"archive is empty: {archive_path}")
        if len(data) > settings.SEMGREP_MAX_UPLOAD_BYTES:
            raise SemgrepError(
                f"archive is {len(data)} bytes but the service accepts at "
                f"most {settings.SEMGREP_MAX_UPLOAD_BYTES}"
            )

        params: dict[str, str] = {"timeout": str(int(scan_budget))}
        if languages:
            params["languages"] = ",".join(languages)
        files = {"file": ("scan.tar.gz", data, "application/gzip")}
        url = f"{self.base_url}/scan"
        http_timeout = scan_budget + CLIENT_GRACE_SECONDS

        last_failure = "no attempt made"
        async with httpx.AsyncClient(
            transport=self._transport, timeout=http_timeout
        ) as client:
            for attempt in range(self.max_retries + 1):
                if attempt:
                    await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                try:
                    response = await client.post(url, params=params, files=files)
                except httpx.HTTPError as exc:
                    last_failure = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "semgrep scan attempt %d/%d failed: %s",
                        attempt + 1,
                        self.max_retries + 1,
                        last_failure,
                    )
                    continue

                if response.status_code == 200:
                    return self._parse_report(response)

                detail = self._detail(response)
                if response.status_code in _RETRYABLE_STATUSES:
                    last_failure = f"HTTP {response.status_code}: {detail}"
                    logger.warning(
                        "semgrep scan attempt %d/%d got %s",
                        attempt + 1,
                        self.max_retries + 1,
                        last_failure,
                    )
                    continue
                raise SemgrepError(
                    f"semgrep service rejected the scan: "
                    f"HTTP {response.status_code}: {detail}"
                )

        raise SemgrepError(
            f"semgrep service unreachable after "
            f"{self.max_retries + 1} attempt(s): {last_failure}"
        )

    @staticmethod
    def _parse_report(response: httpx.Response) -> dict:
        try:
            report = response.json()
        except ValueError as exc:
            raise SemgrepError(
                "semgrep service returned invalid JSON: " f"{response.text[:200]}"
            ) from exc
        if not isinstance(report, dict) or not isinstance(report.get("results"), list):
            raise SemgrepError(
                "semgrep service response is not a semgrep report "
                "(missing 'results' list)"
            )
        return report

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:300]
        if isinstance(payload, dict):
            detail = (
                payload.get("detail") or payload.get("error") or payload.get("message")
            )
            if detail:
                return str(detail)[:300]
        return response.text[:300]


def build_scan_archive(files: list[dict], dest: Path) -> int:
    """Pack ``[{"filename", "content"}]`` entries into a tar.gz at ``dest``.

    The upload payload for ``POST /scan`` — mirrors SonarQube's
    ``write_files_to_temp_dir`` guards: empty contents are skipped,
    absolute paths are stripped of the leading slash, and path traversal
    (``..`` segments) is rejected with a warning. Returns the number of
    members written (0 = nothing scannable; callers must not upload).
    """
    written = 0
    with tarfile.open(dest, "w:gz") as tar:
        for file in files:
            filename = str(file.get("filename") or "").strip().lstrip("/")
            content = file.get("content")
            if not filename or not content:
                continue
            if ".." in filename.split("/"):
                logger.warning(
                    "Skipping file with unsafe path in scan archive: %s",
                    file.get("filename"),
                )
                continue

            data = (
                content.encode("utf-8", errors="replace")
                if isinstance(content, str)
                else bytes(content)
            )
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
            written += 1
    return written
