"""normalize_semgrep: semgrep JSON report -> NormalizedFinding.

The fixture is built from REAL semgrep 1.178.0 output against the baked
packs (p/default + p/security-audit): 3 live findings (eval, pickle,
subprocess) plus 2 synthetic edge cases (INFO+correctness, unknown
severity+style). Live check_ids carry the config-dir prefix
(``rules-packed.`` / ``semgrep-rules.``) — prefix stripping is asserted,
not assumed away.
"""

import json
from pathlib import Path

from app.services.normalizers import normalize_semgrep
from app.services.normalizers.semgrep import (
    strip_check_id_prefix,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load() -> dict:
    return json.loads((FIXTURES / "semgrep_report.json").read_text(encoding="utf-8"))


def _by_rule() -> dict:
    return {f.rule_id: f for f in normalize_semgrep(_load())}


def _find(rule_fragment: str):
    findings = normalize_semgrep(_load())
    return next(f for f in findings if rule_fragment in f.rule_id)


# --- helpers ----------------------------------------------------------------


def test_strip_config_prefix():
    # Config-dir prefix (local run) is dropped; namespace ids untouched.
    assert (
        strip_check_id_prefix("semgrep-rules.python.lang.security.audit.eval-detected")
        == "python.lang.security.audit.eval-detected"
    )
    assert strip_check_id_prefix("python.style.x.y") == "python.style.x.y"
    # Degenerate inputs pass through instead of exploding.
    assert strip_check_id_prefix("") == ""
    assert strip_check_id_prefix("nodot") == "nodot"
    # Empty remainder after the dot is kept as-is.
    assert strip_check_id_prefix("weird.") == "weird."


def test_multi_segment_config_prefix_is_stripped():
    # Live in-cluster check_ids carry the FULL --config path flattened to
    # dots: /opt/semgrep-rules -> "opt.semgrep-rules." — TWO segments,
    # which the old single-segment strip left half in place.
    assert (
        strip_check_id_prefix(
            "opt.semgrep-rules.python.lang.security.audit.eval-detected"
            ".eval-detected"
        )
        == "python.lang.security.audit.eval-detected.eval-detected"
    )
    assert (
        strip_check_id_prefix(
            "opt.semgrep-rules.dockerfile.security.last-user-is-root"
            ".last-user-is-root"
        )
        == "dockerfile.security.last-user-is-root.last-user-is-root"
    )
    # No known namespace anywhere: returned unchanged (never stripped
    # down to the last segment).
    assert strip_check_id_prefix("myorg.custom.rule") == "myorg.custom.rule"


# --- severity / category maps ----------------------------------------------


def test_severity_map_covers_all_native_levels():
    from app.services.normalizers.semgrep import SEVERITY_MAP

    assert SEVERITY_MAP == {
        "ERROR": "high",
        "WARNING": "medium",
        "INFO": "info",
    }


def test_live_findings_severity_mapping():
    assert _find("eval-detected").severity == "medium"  # WARNING
    assert _find("avoid-pickle").severity == "medium"  # WARNING
    assert _find("subprocess-shell-true").severity == "high"  # ERROR


def test_edge_case_severities():
    assert _find("dict-modify-while-iterate").severity == "info"  # INFO
    # Unknown future native level degrades to the schema default.
    assert _find("str-equality").severity == "info"


def test_category_mapping():
    # metadata.category == "security" (with CWE) -> vulnerability.
    assert _find("eval-detected").category == "vulnerability"
    assert _find("avoid-pickle").category == "vulnerability"
    # correctness segment (no security metadata) -> bug.
    assert _find("dict-modify-while-iterate").category == "bug"
    # style namespace, empty metadata -> best_practice catch-all.
    assert _find("str-equality").category == "best_practice"


def test_rule_ids_are_prefix_free_namespaces():
    findings = normalize_semgrep(_load())
    for f in findings:
        assert "." in f.rule_id, f.rule_id
        # The config-dir prefix never survives normalization.
        assert not f.rule_id.startswith(("semgrep-rules.", "rules-packed.")), f.rule_id
    assert _by_rule().keys() == {
        "python.lang.security.audit.eval-detected.eval-detected",
        "python.lang.security.deserialization.pickle.avoid-pickle",
        ("python.lang.security.audit.subprocess-shell-true" ".subprocess-shell-true"),
        (
            "python.lang.correctness.dict-modify-while-iterate"
            ".dict-modify-while-iterate"
        ),
        "python.style.equality-as-str.str-equality",
    }


# --- paths / lines ----------------------------------------------------------


def test_paths_pass_through_untouched():
    assert _find("eval-detected").file_path == "vuln/app.py"
    assert _find("dict-modify-while-iterate").file_path == "src/utils.py"


# --- path reconciliation against the workspace (live service) ---------------


def _live_report(path: str) -> dict:
    """One result shaped exactly like the deployed service returns it."""
    return {
        "results": [
            {
                "check_id": (
                    "opt.semgrep-rules.python.lang.security.audit.eval-detected"
                ),
                "path": path,
                "start": {"line": 14, "col": 1},
                "end": {"line": 14, "col": 20},
                "extra": {"message": "Detected eval().", "severity": "WARNING"},
            }
        ]
    }


def test_absolute_service_paths_are_reconciled_to_the_workspace():
    # The service scans a per-request temp dir, so semgrep reports
    # /tmp/semgrep-scan-<rand>/src/<archive member>. The archive members
    # are the workspace filenames -> the path must land back on one.
    (finding,) = normalize_semgrep(
        _live_report("/tmp/semgrep-scan-x7y8/src/vuln/app.py"),
        files=[{"filename": "vuln/app.py", "content": "x = 1\n"}],
    )
    assert finding.file_path == "vuln/app.py"
    # Same run also carries the two-segment prefix — stripped too.
    assert finding.rule_id == ("python.lang.security.audit.eval-detected")
    assert finding.severity == "medium"  # WARNING


def test_longest_workspace_suffix_wins():
    # "app.py" is a suffix of "vuln/app.py" — the deeper name must win.
    files = [{"filename": "app.py"}, {"filename": "vuln/app.py"}]
    (finding,) = normalize_semgrep(
        _live_report("/tmp/semgrep-scan-x7y8/src/vuln/app.py"), files=files
    )
    assert finding.file_path == "vuln/app.py"
    # And a path that IS just app.py resolves to the shallow name.
    (shallow,) = normalize_semgrep(
        _live_report("/tmp/semgrep-scan-x7y8/src/app.py"), files=files
    )
    assert shallow.file_path == "app.py"


def test_paths_pass_through_without_workspace_or_match():
    # No workspace given: verbatim (pre-reconciliation behaviour).
    (no_ws,) = normalize_semgrep(_live_report("/tmp/x/src/app.py"))
    assert no_ws.file_path == "/tmp/x/src/app.py"
    # Workspace given but no filename matches: untouched, not guessed.
    (unmatched,) = normalize_semgrep(
        _live_report("/tmp/x/src/other.py"), files=[{"filename": "app.py"}]
    )
    assert unmatched.file_path == "/tmp/x/src/other.py"
    # Relative path already naming a workspace file: unchanged.
    (relative,) = normalize_semgrep(
        _live_report("vuln/app.py"), files=[{"filename": "vuln/app.py"}]
    )
    assert relative.file_path == "vuln/app.py"
    # The raw payload keeps the ORIGINAL path for debugging.
    assert relative.raw["path"] == "vuln/app.py"


def test_line_ranges():
    eval_finding = _find("eval-detected")
    assert eval_finding.line_start == 14
    assert eval_finding.line_end == 14
    # Synthetic finding spans a known multi-column range on one line.
    assert _find("dict-modify-while-iterate").line_start == 42


# --- metadata ---------------------------------------------------------------


def test_cwe_is_normalized_to_bare_ids():
    # "CWE-95: Improper Neutralization..." -> "CWE-95" (Sonar-compatible).
    assert _find("eval-detected").cwe == ["CWE-95"]
    assert _find("avoid-pickle").cwe == ["CWE-502"]
    # No CWE in metadata -> [].
    assert _find("dict-modify-while-iterate").cwe == []


def test_owasp_verbatim():
    owasp = _find("eval-detected").owasp
    assert "A03:2021 - Injection" in owasp
    assert len(owasp) >= 1
    assert _find("dict-modify-while-iterate").owasp == []


def test_references_from_metadata():
    refs = _find("subprocess-shell-true").references
    assert any("docs.python.org" in r for r in refs)
    assert all(r.startswith(("http://", "https://")) for r in refs)
    # source-rule-url is folded in as a reference too.
    eval_refs = _find("eval-detected").references
    assert any("bandit" in r for r in eval_refs)
    assert _find("dict-modify-while-iterate").references == []


def test_snippet_message_and_title():
    eval_finding = _find("eval-detected")
    # snippet = extra.lines verbatim (Step 6 enriches it from the workspace).
    assert eval_finding.snippet == eval_finding.raw["extra"]["lines"]
    assert eval_finding.message == eval_finding.raw["extra"]["message"]
    # title = first message line, single line.
    assert eval_finding.title.startswith("Detected the use of eval().")
    assert "\n" not in eval_finding.title
    # Multi-line message -> title is line 1 only.
    correctness = _find("dict-modify-while-iterate")
    assert correctness.title == "Do not modify a dict while iterating over it."
    assert "\n" not in correctness.title


# --- identity / tolerance ---------------------------------------------------


def test_all_findings_are_semgrep_with_stable_unique_ids():
    findings = normalize_semgrep(_load())
    assert len(findings) == 5
    assert all(f.tool == "semgrep" for f in findings)
    # Deterministic: same input twice -> same fingerprints.
    again = normalize_semgrep(_load())
    assert [f.id for f in findings] == [f.id for f in again]
    assert len({f.id for f in findings}) == len(findings)
    # raw payload preserved verbatim for debugging.
    assert all(f.raw.get("check_id") for f in findings)


def test_empty_and_malformed_reports_yield_no_findings():
    assert normalize_semgrep({"results": []}) == []
    assert normalize_semgrep({}) == []
    assert normalize_semgrep({"results": "not-a-list"}) == []
    # Non-object entries are skipped, not fatal.
    assert normalize_semgrep({"results": [None, 42]}) == []
    # One malformed object among good ones keeps the good ones.
    partial = {
        "results": [
            {"check_id": "python.style.a.b", "extra": {"message": "m"}},
            {"check_id": "python.style.c.d"},  # missing extra -> tolerated
        ]
    }
    findings = normalize_semgrep(partial)
    assert len(findings) == 2
    assert all(f.tool == "semgrep" for f in findings)
