"""Service configuration — plain environment-driven constants.

Values are read once at import and referenced as ``config.<NAME>`` at call
time, so tests can monkeypatch them with
``monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", ...)``.
"""

import os


def _int_env(name: str, default: int) -> int:
    """Integer env var with a safe fallback (bad values keep the default)."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# --- concurrency ------------------------------------------------------------
# How many semgrep processes may run at once (also bounds temp-disk use).
MAX_CONCURRENT_SCANS = _int_env("MAX_CONCURRENT_SCANS", 2)

# --- upload / extraction limits (zip-bomb + disk guards) --------------------
MAX_UPLOAD_BYTES = _int_env("MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
MAX_EXTRACTED_BYTES = _int_env("MAX_EXTRACTED_BYTES", 64 * 1024 * 1024)
MAX_EXTRACTED_FILES = _int_env("MAX_EXTRACTED_FILES", 5000)
READ_CHUNK_BYTES = 1024 * 1024

# --- semgrep ----------------------------------------------------------------
SEMGREP_BINARY = os.getenv("SEMGREP_BINARY", "semgrep")
SEMGREP_RULES_DIR = os.getenv("SEMGREP_RULES_DIR", "/opt/semgrep-rules")
# Default per-request scan timeout; requests may lower/raise it up to the max.
SEMGREP_TIMEOUT_SECONDS = _int_env("SEMGREP_TIMEOUT_SECONDS", 60)
MAX_SCAN_TIMEOUT_SECONDS = _int_env("MAX_SCAN_TIMEOUT_SECONDS", 600)
# Extra seconds beyond the requested timeout before the subprocess is killed.
KILL_GRACE_SECONDS = _int_env("KILL_GRACE_SECONDS", 30)
