"""Static guard: frontend renders stored text through interpolation only.

Plan Step 9: "Notes stored as-is (plain text); frontend renders escaped
(Angular interpolation default — asserted by a test that no binding uses
``innerHTML``/``bypassSecurityTrust``)."

Reviewer notes, LLM output and scanner findings are stored verbatim, so
the rendering side must never opt out of Angular's escaping. This test
scans every ``.ts``/``.html`` under ``frontend/src`` for ``[innerHTML]``
bindings and ``bypassSecurityTrust*`` calls and fails with the offending
file:line if either appears.
"""

import re
from pathlib import Path

import pytest

_FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"

# Angular bindings that bypass escaping, and the sanitizer escape hatch.
_UNSAFE = re.compile(r"\[innerHTML\]|\[outerHTML\]|\bbypassSecurityTrust")


def _iter_sources() -> list[Path]:
    if not _FRONTEND_SRC.is_dir():
        return []
    return [
        path
        for path in sorted(_FRONTEND_SRC.rglob("*"))
        if path.is_file() and path.suffix in {".ts", ".html"}
    ]


def test_frontend_binds_no_innerhtml_or_sanitizer_bypass():
    sources = _iter_sources()
    if not sources:  # frontend not checked out (backend-only environment)
        pytest.skip("frontend/src not available")

    offenders = [
        f"{path.relative_to(_FRONTEND_SRC)}:{lineno}"
        for path in sources
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if _UNSAFE.search(line)
    ]
    assert offenders == [], (
        "Stored text must render via Angular interpolation only — "
        "unsafe bindings found: " + ", ".join(offenders)
    )
