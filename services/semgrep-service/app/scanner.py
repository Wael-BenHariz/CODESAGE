"""Run the semgrep CLI (OSS, metrics off) and parse its JSON output.

Exit-code contract handled here so callers never see raw codes:

- ``0`` — completed, no findings (JSON on stdout)
- ``1`` — completed **with findings** (JSON on stdout). With ``--json``
  this is NOT an error; if stdout is not valid JSON the run failed.
- ``>= 2`` — real error (bad config, crash): raises ``ScanError`` with
  the stderr tail.

The subprocess is launched with ``asyncio.create_subprocess_exec`` (never
a shell string) and hard-killed after ``timeout + KILL_GRACE_SECONDS``.
"""

import asyncio
import json
import logging
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app import config

logger = logging.getLogger(__name__)

# Language filter globs, keyed by the names the API accepts. Both the
# basename and the recursive form are emitted so matches work whether
# semgrep anchors the pattern at the scan root or not.
LANGUAGE_GLOBS: dict[str, tuple[str, ...]] = {
    "bash": ("*.sh", "*.bash"),
    "c": ("*.c", "*.h"),
    "cpp": ("*.cc", "*.cpp", "*.cxx", "*.hh", "*.hpp", "*.hxx"),
    "csharp": ("*.cs",),
    "dockerfile": ("Dockerfile",),
    "go": ("*.go",),
    "java": ("*.java",),
    "javascript": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "json": ("*.json",),
    "kotlin": ("*.kt", "*.kts"),
    "lua": ("*.lua",),
    "php": ("*.php", "*.php3", "*.php4", "*.php5"),
    "python": ("*.py", "*.pyi"),
    "ruby": ("*.rb", "*.rake"),
    "rust": ("*.rs",),
    "scala": ("*.scala", "*.sc"),
    "solidity": ("*.sol",),
    "swift": ("*.swift",),
    "terraform": ("*.tf", "*.tfvars", "*.hcl"),
    "typescript": ("*.ts", "*.tsx"),
    "yaml": ("*.yml", "*.yaml"),
}


class ScanError(Exception):
    """Semgrep failed (exit >= 2, invalid JSON, or bad invocation)."""


class ScanTimeout(ScanError):
    """Semgrep exceeded the hard time limit and was killed."""


def _include_globs(languages: Sequence[str]) -> list[str]:
    """Expand language names to ``--include`` glob patterns."""
    globs: list[str] = []
    for language in languages:
        patterns = LANGUAGE_GLOBS.get(language)
        if patterns is None:
            raise ValueError(f"unsupported language: {language}")
        for pattern in patterns:
            for form in (pattern, f"**/{pattern}"):
                if form not in globs:
                    globs.append(form)
    return globs


def build_command(
    target_dir: Path,
    timeout: int,
    languages: Sequence[str] | None = None,
) -> list[str]:
    """Assemble the semgrep argv — OSS rules only, never a shell string."""
    command = [
        config.SEMGREP_BINARY,
        "scan",
        "--json",
        "--metrics=off",
        "--disable-version-check",
        "--timeout",
        str(timeout),
        "--config",
        str(config.SEMGREP_RULES_DIR),
    ]
    if languages:
        for pattern in _include_globs(languages):
            command.extend(("--include", pattern))
    command.append(str(target_dir))
    return command


async def run_semgrep(
    target_dir: Path,
    *,
    timeout: int,
    languages: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Scan ``target_dir`` and return the parsed semgrep JSON report.

    Raises ``ScanTimeout`` after ``timeout + KILL_GRACE_SECONDS`` and
    ``ScanError`` for exit codes >= 2 or unparseable output.
    """
    command = build_command(target_dir, timeout, languages)
    logger.info("semgrep: %s", " ".join(command))

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ScanError(f"failed to launch semgrep: {exc}") from exc

    hard_timeout = timeout + config.KILL_GRACE_SECONDS
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=hard_timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise ScanTimeout(f"semgrep exceeded the {hard_timeout}s hard limit") from None

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    returncode = process.returncode

    if returncode in (0, 1):
        if not out.strip():
            if returncode == 1:
                raise ScanError("semgrep exited 1 but produced no JSON output")
            # rc 0 with empty stdout: treat as an empty report.
            return {"results": [], "errors": []}
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError as exc:
            raise ScanError(
                f"semgrep produced invalid JSON (exit {returncode}): " f"{out[:400]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ScanError(f"semgrep JSON is not an object (exit {returncode})")
        logger.info("semgrep finished: %d result(s)", len(parsed.get("results") or []))
        return parsed

    tail = "\n".join(err.splitlines()[-20:]) or out[-1000:]
    raise ScanError(f"semgrep failed with exit {returncode}: {tail}")


def semgrep_available() -> bool:
    """True when the semgrep binary can be found on PATH."""
    return (
        shutil.which(config.SEMGREP_BINARY) is not None
        or Path(config.SEMGREP_BINARY).is_file()
    )
