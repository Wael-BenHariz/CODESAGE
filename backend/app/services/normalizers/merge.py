"""Cross-tool merge: dedup the same defect found by more than one analyzer.

``merge_findings(sonar_findings, semgrep_findings)`` produces one
deterministic list where the FIRST occurrence of a defect wins the slot
(``tool`` = primary producer) and records who else saw it in
``also_detected_by``.

Two findings are considered the same defect only when ALL hold:

1. **different tools** — same-tool hits are distinct rules even on the
   same line (e.g. two sonar S-rules), never merged;
2. same ``file_path``;
3. their line ranges overlap (a finding without a line never merges —
   too little evidence to claim identity);
4. they share at least one **CWE id** — rule ids and titles differ
   across tools, CWE is the stable cross-tool identity (a finding
   without a CWE never merges).

The survivor keeps its position, title, message, and raw payload; on a
merge it takes the **stronger** severity and the union of
CWE/OWASP/references. Findings that match nothing are returned as-is
(``also_detected_by`` stays empty).
"""

from collections.abc import Iterable, Sequence

from app.services.normalizers.schema import NormalizedFinding

# Unified severity ordering (see schema.Severity).
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _overlaps(a: NormalizedFinding, b: NormalizedFinding) -> bool:
    """True when both findings have line info and their ranges intersect."""
    if a.line_start is None or b.line_start is None:
        return False
    a_end = a.line_end if a.line_end is not None else a.line_start
    b_end = b.line_end if b.line_end is not None else b.line_start
    return a.line_start <= b_end and b.line_start <= a_end


def _same_defect(a: NormalizedFinding, b: NormalizedFinding) -> bool:
    return (
        a.tool != b.tool
        and a.file_path == b.file_path
        and _overlaps(a, b)
        and bool(set(a.cwe) & set(b.cwe))
    )


def _union(first: Sequence[str], second: Sequence[str]) -> list[str]:
    """Concatenation deduped, order-preserving."""
    return list(dict.fromkeys([*first, *second]))


def merge_findings(
    *groups: Iterable[NormalizedFinding],
) -> list[NormalizedFinding]:
    """Merge tool outputs into one deduped, deterministically ordered list.

    Groups are consumed in argument order (pass SonarQube first to make
    it the primary tool for merged defects). Mutates merged survivors;
    inputs are freshly normalized lists in practice.
    """
    merged: list[NormalizedFinding] = []

    for group in groups:
        for finding in group:
            match = next((m for m in merged if _same_defect(m, finding)), None)
            if match is None:
                finding.also_detected_by = []
                merged.append(finding)
                continue

            # Same defect, other tool: record it, strengthen the survivor.
            match.also_detected_by = _union(match.also_detected_by, [finding.tool])
            if _SEVERITY_RANK[finding.severity] > _SEVERITY_RANK[match.severity]:
                match.severity = finding.severity
            match.cwe = _union(match.cwe, finding.cwe)
            match.owasp = _union(match.owasp, finding.owasp)
            match.references = _union(match.references, finding.references)

    return merged
