"""merge_findings: cross-tool dedup with ``also_detected_by``.

Dedup identity = different tools + same file + overlapping lines +
shared CWE (see merge.py docstring). Same-tool hits, missing CWE, or
missing lines are never merged.
"""

from app.services.normalizers import merge_findings
from app.services.normalizers.schema import NormalizedFinding


def _f(
    tool: str = "sonarqube",
    *,
    rule_id: str = "r1",
    file_path: str = "src/a.py",
    line_start: int | None = 10,
    line_end: int | None = None,
    cwe: list[str] | None = None,
    owasp: list[str] | None = None,
    references: list[str] | None = None,
    severity: str = "medium",
    message: str = "problem",
) -> NormalizedFinding:
    return NormalizedFinding(
        tool=tool,  # type: ignore[arg-type]
        rule_id=rule_id,
        message=message,
        severity=severity,  # type: ignore[arg-type]
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        cwe=cwe or [],
        owasp=owasp or [],
        references=references or [],
    )


# --- merge criteria ---------------------------------------------------------


def test_cross_tool_same_file_line_and_cwe_merges():
    sonar = _f(cwe=["CWE-95"], severity="low")
    semgrep = _f(tool="semgrep", cwe=["CWE-95"], severity="high")

    merged = merge_findings([sonar], [semgrep])

    assert len(merged) == 1
    survivor = merged[0]
    assert survivor.tool == "sonarqube"  # first group = primary
    assert survivor.also_detected_by == ["semgrep"]
    # Stronger severity wins.
    assert survivor.severity == "high"


def test_different_cwe_never_merges():
    merged = merge_findings(
        [_f(cwe=["CWE-89"])],
        [_f(tool="semgrep", cwe=["CWE-95"])],
    )
    assert len(merged) == 2
    assert all(f.also_detected_by == [] for f in merged)


def test_missing_cwe_never_merges():
    merged = merge_findings(
        [_f(cwe=[])],
        [_f(tool="semgrep", cwe=["CWE-95"])],
    )
    assert len(merged) == 2
    # And the reverse: neither side carries a CWE.
    assert len(merge_findings([_f()], [_f(tool="semgrep")])) == 2


def test_non_overlapping_lines_never_merge():
    merged = merge_findings(
        [_f(line_start=10, cwe=["CWE-95"])],
        [_f(tool="semgrep", line_start=42, cwe=["CWE-95"])],
    )
    assert len(merged) == 2


def test_overlapping_multi_line_ranges_merge():
    sonar = _f(line_start=10, line_end=20, cwe=["CWE-95"])
    semgrep = _f(tool="semgrep", line_start=18, line_end=30, cwe=["CWE-95"])
    assert len(merge_findings([sonar], [semgrep])) == 1
    # Adjacent single-line findings on the same line also overlap.
    assert (
        len(
            merge_findings(
                [_f(line_start=10, cwe=["CWE-95"])],
                [_f(tool="semgrep", line_start=10, cwe=["CWE-95"])],
            )
        )
        == 1
    )


def test_missing_line_never_merges():
    merged = merge_findings(
        [_f(line_start=None, cwe=["CWE-95"])],
        [_f(tool="semgrep", line_start=10, cwe=["CWE-95"])],
    )
    assert len(merged) == 2


def test_different_file_never_merges():
    merged = merge_findings(
        [_f(file_path="a.py", cwe=["CWE-95"])],
        [_f(tool="semgrep", file_path="b.py", cwe=["CWE-95"])],
    )
    assert len(merged) == 2


def test_same_tool_never_merges():
    merged = merge_findings(
        [_f(rule_id="r1", cwe=["CWE-95"])],
        [_f(rule_id="r2", cwe=["CWE-95"])],
    )
    assert len(merged) == 2
    assert all(f.also_detected_by == [] for f in merged)


# --- survivor strengthening -------------------------------------------------


def test_survivor_takes_union_of_metadata():
    sonar = _f(cwe=["CWE-89"], owasp=["A03:2021 - Injection"], severity="info")
    semgrep = _f(
        tool="semgrep",
        # Shares CWE-89 (merge key) but adds CWE-95 -> union on the survivor.
        cwe=["CWE-89", "CWE-95"],
        owasp=["A03:2021 - Injection", "A01:2017 - Injection"],
        references=["https://example.com/rule"],
        severity="critical",
    )

    (survivor,) = merge_findings([sonar], [semgrep])

    assert survivor.severity == "critical"
    assert survivor.cwe == ["CWE-89", "CWE-95"]
    assert survivor.owasp == ["A03:2021 - Injection", "A01:2017 - Injection"]
    assert survivor.references == ["https://example.com/rule"]


def test_multiple_findings_absorb_into_one_survivor():
    sonar = _f(cwe=["CWE-95"])
    semgrep_a = _f(tool="semgrep", rule_id="a", cwe=["CWE-95"])
    semgrep_b = _f(tool="semgrep", rule_id="b", cwe=["CWE-95"])

    merged = merge_findings([sonar], [semgrep_a, semgrep_b])

    assert len(merged) == 1
    # also_detected_by lists each tool once.
    assert merged[0].also_detected_by == ["semgrep"]


# --- structure / determinism ------------------------------------------------


def test_group_order_and_first_occurrence_win():
    sonar = _f(cwe=["CWE-95"])
    semgrep = _f(tool="semgrep", cwe=["CWE-95"])
    other = _f(rule_id="r2", cwe=["CWE-120"])

    merged = merge_findings([other, sonar], [semgrep])

    # Unrelated sonar finding keeps its slot; merged pair sits after it.
    assert [f.rule_id for f in merged] == ["r2", "r1"]
    assert merged[1].tool == "sonarqube"


def test_empty_groups_yield_empty_list():
    assert merge_findings() == []
    assert merge_findings([], []) == []
    assert merge_findings([_f()]) == [_f()]


def test_stale_also_detected_by_is_reset_for_unmerged():
    solo = _f()
    solo.also_detected_by = ["semgrep"]  # stale annotation
    (result,) = merge_findings([solo], [])
    assert result.also_detected_by == []


def test_merge_is_deterministic():
    def run():
        return merge_findings(
            [_f(cwe=["CWE-95"]), _f(rule_id="r2", cwe=["CWE-120"])],
            [_f(tool="semgrep", cwe=["CWE-95"])],
        )

    first, second = run(), run()
    assert [f.id for f in first] == [f.id for f in second]
    assert [f.also_detected_by for f in first] == [f.also_detected_by for f in second]
