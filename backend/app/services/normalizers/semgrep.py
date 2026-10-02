"""Normalize Semgrep output into the unified finding schema.

Verified against real semgrep 1.178.0 output from the baked packs
(p/default + p/security-audit):

- ``check_id`` is prefixed with the config parent-dir name
  (``semgrep-rules.<rule id>`` in the image, ``rules-packed.<rule id>``
  locally) — stripped here so rule ids are the canonical
  ``<namespace>.<path>`` form regardless of where the rules live.
- ``extra.severity``: ``ERROR | WARNING | INFO`` (no critical in OSS,
  ERROR is semgrep's strongest) → high / medium / info.
- Category comes from ``extra.metadata.category`` (``"security"`` on the
  audit packs) or a CWE; correctness/typecheck segments map to ``bug``
  (mirrors Sonar's bug type); everything else is the schema's
  best_practice catch-all (style/lint).
"""

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.normalizers.schema import NormalizedFinding

logger = logging.getLogger(__name__)

# Semgrep severity levels (fixed enum in the OSS engine) -> unified scale.
SEVERITY_MAP: dict[str, str] = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "info",
}

# First segment of a canonical rule id (namespace). Observed over both
# baked packs; extra common semgrep languages included so a pack refresh
# that adds a namespace doesn't get its prefix mis-stripped.
RULE_NAMESPACES = frozenset(
    {
        "bash",
        "c",
        "clojure",
        "csharp",
        "dart",
        "dockerfile",
        "elixir",
        "generic",
        "go",
        "groovy",
        "html",
        "java",
        "javascript",
        "json",
        "kotlin",
        "lisp",
        "lua",
        "ocaml",
        "package_managers",
        "perl",
        "php",
        "problem-based-packs",
        "python",
        "r",
        "ruby",
        "rust",
        "scala",
        "semgrep",
        "solidity",
        "swift",
        "terraform",
        "trailofbits",
        "typescript",
        "xml",
        "yaml",
    }
)

# Leading "CWE-95: Description" -> "CWE-95" (matches Sonar's tag format
# so cross-tool dedup can key on identical CWE ids).
_CWE_ID = re.compile(r"CWE-\d+", re.IGNORECASE)

TITLE_MAX = 160


def strip_check_id_prefix(check_id: str) -> str:
    """Drop the config-dir prefix semgrep prepends to every check_id.

    ``semgrep-rules.python.lang...`` -> ``python.lang...``; an id that
    already starts with a known namespace is returned unchanged.
    """
    first, sep, rest = check_id.partition(".")
    if not sep or not rest or first in RULE_NAMESPACES:
        return check_id
    return rest


def _title(message: str) -> str:
    """First line of the message, truncated — same rule as sonarqube.py."""
    first = message.strip().splitlines()[0].strip() if message.strip() else ""
    if len(first) > TITLE_MAX:
        return first[: TITLE_MAX - 1].rstrip() + "…"
    return first


def _category(check_id: str, metadata: Mapping[str, Any], cwe: list[str]) -> str:
    if cwe or metadata.get("category") == "security":
        return "vulnerability"
    if ".correctness." in check_id or ".typecheck." in check_id:
        return "bug"
    if ".performance." in check_id:
        return "code_smell"
    return "best_practice"


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value]
    return []


def _extract_cwe(metadata: Mapping[str, Any]) -> list[str]:
    """Normalize ``"CWE-502: Deserialization..."`` entries to ``CWE-502``."""
    found: list[str] = []
    for entry in _as_list(metadata.get("cwe")):
        match = _CWE_ID.search(entry)
        if match and match.group(0).upper() not in found:
            found.append(match.group(0).upper())
    return found


def _extract_references(metadata: Mapping[str, Any]) -> list[str]:
    """Reference URLs: explicit list + rule source links, deduped."""
    refs: list[str] = []
    for key in ("references", "source-rule-url", "source"):
        for value in _as_list(metadata.get(key)):
            value = value.strip()
            if value.startswith(("http://", "https://")) and value not in refs:
                refs.append(value)
    return refs


def normalize_semgrep(report: Mapping[str, Any]) -> list[NormalizedFinding]:
    """Map one semgrep JSON report (``{"results": [...]}``) to findings.

    Tolerant by design: missing/empty ``results`` yields ``[]``, and a
    malformed entry is skipped with a warning instead of failing the
    whole scan.
    """
    results = report.get("results")
    if not isinstance(results, list):
        return []

    findings: list[NormalizedFinding] = []
    for raw in results:
        if not isinstance(raw, Mapping):
            logger.warning("semgrep: skipping non-object result: %r", raw)
            continue
        try:
            findings.append(_normalize_one(raw))
        except Exception:  # one bad finding must not sink the scan
            logger.warning(
                "semgrep: skipping malformed result: %r",
                dict(raw),
                exc_info=True,
            )
    return findings


def _normalize_one(raw: Mapping[str, Any]) -> NormalizedFinding:
    extra = raw.get("extra")
    extra = extra if isinstance(extra, Mapping) else {}
    metadata = extra.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}

    check_id = str(raw.get("check_id") or "")
    rule_id = strip_check_id_prefix(check_id)
    message = str(extra.get("message") or "")
    cwe = _extract_cwe(metadata)

    native_severity = str(extra.get("severity") or "").upper()
    severity = SEVERITY_MAP.get(native_severity, "info")
    if native_severity not in SEVERITY_MAP:
        logger.warning(
            "semgrep: unknown severity %r on %s — defaulting to info",
            extra.get("severity"),
            rule_id,
        )

    start = raw.get("start")
    start = start if isinstance(start, Mapping) else {}
    end = raw.get("end")
    end = end if isinstance(end, Mapping) else {}
    line_start = start.get("line")
    line_end = end.get("line") or line_start

    return NormalizedFinding(
        tool="semgrep",
        rule_id=rule_id,
        title=_title(message),
        message=message,
        severity=severity,  # type: ignore[arg-type]
        category=_category(rule_id, metadata, cwe),  # type: ignore[arg-type]
        file_path=str(raw.get("path") or ""),
        line_start=int(line_start) if line_start is not None else None,
        line_end=int(line_end) if line_end is not None else None,
        snippet=str(extra.get("lines")) if extra.get("lines") else None,
        cwe=cwe,
        owasp=_as_list(metadata.get("owasp")),
        references=_extract_references(metadata),
        raw=dict(raw),
    )
