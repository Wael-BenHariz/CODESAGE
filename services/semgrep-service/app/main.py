"""FastAPI app: liveness/readiness + ``POST /scan`` (multipart tar.gz).

The service is stateless: each request gets its own temp dir (cleaned up
on exit) and one slot of the ``MAX_CONCURRENT_SCANS`` semaphore.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from app import config, extractor, scanner

logger = logging.getLogger(__name__)


def _parse_languages(raw: str | None) -> list[str] | None:
    """Comma-separated language filter -> list (None when absent)."""
    if not raw or not raw.strip():
        return None
    languages = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not languages:
        return None
    unknown = [lang for lang in languages if lang not in scanner.LANGUAGE_GLOBS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unsupported language(s): {', '.join(unknown)}; "
                f"supported: {', '.join(sorted(scanner.LANGUAGE_GLOBS))}"
            ),
        )
    return languages


async def _save_upload(upload: UploadFile, target: Path) -> int:
    """Buffer the upload in memory (capped), write it via a thread."""
    buffer = bytearray()
    while chunk := await upload.read(config.READ_CHUNK_BYTES):
        buffer.extend(chunk)
        if len(buffer) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds {config.MAX_UPLOAD_BYTES} bytes",
            )
    await asyncio.to_thread(target.write_bytes, bytes(buffer))
    return len(buffer)


def create_app() -> FastAPI:
    """Application factory (fresh semaphore per app — used by tests too)."""
    app = FastAPI(title="CodeSage Semgrep Scan Service", version="1.0.0")
    app.state.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_SCANS)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        """Readiness: semgrep binary present and rules baked in."""
        problems: list[str] = []
        if not scanner.semgrep_available():
            problems.append(f"semgrep binary not found: {config.SEMGREP_BINARY}")
        rules = Path(config.SEMGREP_RULES_DIR)
        if not rules.is_dir():
            problems.append(f"rules dir missing: {rules}")
        elif not any(rules.rglob("*.yml")) and not any(rules.rglob("*.yaml")):
            problems.append(f"no rule files under {rules}")
        if problems:
            raise HTTPException(status_code=503, detail="; ".join(problems))
        return {"status": "ready", "rules": str(rules)}

    @app.post("/scan")
    async def scan(
        file: UploadFile = File(..., description="tar.gz of source files"),
        languages: str | None = Query(
            None, description="comma-separated language filter"
        ),
        timeout: int | None = Query(
            None, ge=1, description="semgrep timeout in seconds"
        ),
    ) -> dict:
        """Extract a tar.gz safely and scan it with semgrep.

        Returns the semgrep JSON report as-is. 413 = size caps,
        400 = invalid/unsafe archive, 422 = no files / bad params,
        504 = scan timeout, 502 = semgrep failure.
        """
        language_list = _parse_languages(languages)
        effective_timeout = min(
            timeout or config.SEMGREP_TIMEOUT_SECONDS,
            config.MAX_SCAN_TIMEOUT_SECONDS,
        )

        async with app.state.semaphore:
            with tempfile.TemporaryDirectory(prefix="semgrep-scan-") as tmp:
                tmp_path = Path(tmp)
                archive = tmp_path / "upload.tar.gz"
                saved = await _save_upload(file, archive)
                if saved == 0:
                    raise HTTPException(status_code=400, detail="empty upload")

                source_dir = tmp_path / "src"
                try:
                    await asyncio.to_thread(
                        extractor.safe_extract_tar_gz, archive, source_dir
                    )
                except extractor.ExtractError as exc:
                    status = 413 if exc.resource else 400
                    raise HTTPException(status_code=status, detail=str(exc)) from exc

                if not any(path.is_file() for path in source_dir.rglob("*")):
                    raise HTTPException(
                        status_code=422,
                        detail="archive contains no regular files",
                    )

                logger.info(
                    "scan request: %d bytes, timeout=%ds, languages=%s",
                    saved,
                    effective_timeout,
                    language_list or "all",
                )
                try:
                    return await scanner.run_semgrep(
                        source_dir,
                        timeout=effective_timeout,
                        languages=language_list,
                    )
                except scanner.ScanTimeout as exc:
                    raise HTTPException(status_code=504, detail=str(exc)) from exc
                except scanner.ScanError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


app = create_app()
