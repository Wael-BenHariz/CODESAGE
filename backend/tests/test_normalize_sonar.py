"""normalize_sonar: SonarQube issues/hotspots -> NormalizedFinding.

Fixtures mirror real API payloads: ``sonar_issues.json`` is the
``/api/issues/search`` shape (component carries the ``projectKey:`` prefix),
``sonar_hotspots.json`` is the ``/api/hotspots/search`` shape (severity comes
from ``vulnerabilityProbability``).
"""

import json
from pathlib import Path

from app.services.normalizers import normalize_sonar
from app.services.normalizers.sonarqube import (
    strip_component_prefix,
)
from app.services.sonarqube import SonarIssue

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _issue_from_raw(raw: dict) -> SonarIssue:
    """Same shape ``sonarqube.get_issues`` builds — component NOT stripped,
    so the normalizer's own prefix handling is what gets tested."""
    return SonarIssue(
        key=str(raw.get("key") or ""),
        rule=str(raw.get("rule") or ""),
        severity=str(raw.get("severity") or "INFO").upper(),
        type=str(raw.get("type") or "").upper(),
        component=str(raw.get("component") or ""),
        line=raw.get("line"),
        message=str(raw.get("message") or ""),
        effort=raw.get("effort"),
        tags=[str(t) for t in (raw.get("tags") or [])],
    )


def _normalized():
    issues = [_issue_from_raw(r) for r in _load("sonar_issues.json")]
    hotspots = _load("sonar_hotspots.json")
    return issues, hotspots, normalize_sonar(issues, hotspots)


# --- helpers ----------------------------------------------------------------


def test_strip_component_prefix():
    assert strip_component_prefix("proj-key:src/A.java") == "src/A.java"
    assert strip_component_prefix("src/A.java") == "src/A.java"
    assert strip_component_prefix("") == ""


def test_to_line_rejects_bools_and_strings():
    from app.services.normalizers.sonarqube import _to_line

    assert _to_line(7) == 7
    assert _to_line("7") == 7
    assert _to_line(0) is None
    assert _to_line(-1) is None
    assert _to_line(True) is None
    assert _to_line(None) is None
    assert _to_line("abc") is None


# --- severity / category maps ----------------------------------------------


def test_issue_severity_map():
    _, _, findings = _normalized()
    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["java:S2077"].severity == "critical"  # BLOCKER
    assert by_rule["java:S1541"].severity == "medium"  # MAJOR
    assert by_rule["python:S4502"].severity == "low"  # MINOR
    assert by_rule["python:S100"].severity == "info"  # INFO
    # Unknown future value degrades to the schema default.
    assert by_rule["custom:R1"].severity == "info"


def test_issue_category_map():
    _, _, findings = _normalized()
    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["java:S2077"].category == "vulnerability"
    assert by_rule["java:S1541"].category == "code_smell"
    assert by_rule["python:S4502"].category == "bug"
    assert by_rule["python:S100"].category == "code_smell"
    assert by_rule["java:S5766"].category == "security_hotspot"
    assert by_rule["custom:R1"].category == "best_practice"


def test_all_five_native_severities_are_mapped():
    from app.services.normalizers.sonarqube import SEVERITY_MAP

    assert set(SEVERITY_MAP) == {"BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"}
    assert SEVERITY_MAP == {
        "BLOCKER": "critical",
        "CRITICAL": "high",
        "MAJOR": "medium",
        "MINOR": "low",
        "INFO": "info",
    }


# --- paths / lines ----------------------------------------------------------


def test_component_project_prefix_is_stripped():
    _, _, findings = _normalized()
    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["java:S2077"].file_path == "src/main/java/com/app/UserDao.java"
    # Already-relative path passes through untouched.
    assert by_rule["python:S100"].file_path == "app/utils.py"


def test_lines_are_single_line_ranges_or_none():
    _, _, findings = _normalized()
    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["java:S2077"].line_start == 42
    assert by_rule["java:S2077"].line_end == 42
    # File-level issue (no line) stays None.
    assert by_rule["python:S100"].line_start is None
    assert by_rule["python:S100"].line_end is None


# --- hotspots ---------------------------------------------------------------


def test_hotspot_probability_maps_to_severity():
    _, _, findings = _normalized()
    hotspots = [f for f in findings if f.category == "security_hotspot" and f.rule_id]
    by_key = {f.raw["key"]: f for f in hotspots}
    assert by_key["H1"].severity == "high"  # HIGH
    assert by_key["H2"].severity == "medium"  # MEDIUM
    assert by_key["H3"].severity == "low"  # LOW
    # Missing probability degrades to medium.
    assert by_key["H4"].severity == "medium"


def test_hotspots_are_category_security_hotspot_with_stripped_paths():
    _, hotspots, findings = _normalized()
    # Hotspot payloads carry `status`; SonarIssue-derived raw does not.
    hotspot_findings = [f for f in findings if "status" in f.raw]
    assert len(hotspot_findings) == len(hotspots)
    for f in hotspot_findings:
        assert f.category == "security_hotspot"
        assert f.tool == "sonarqube"
        assert not f.file_path.startswith("codesage-review-")
    by_key = {f.raw["key"]: f for f in hotspot_findings}
    assert by_key["H1"].file_path == "app/views.py"
    assert by_key["H2"].file_path == "src/Crypto.java"
    # File-level hotspot (no line).
    assert by_key["H4"].line_start is None


# --- metadata ---------------------------------------------------------------


def test_cwe_and_owasp_extracted_from_tags():
    _, _, findings = _normalized()
    sqli = next(f for f in findings if f.rule_id == "java:S2077")
    assert sqli.cwe == ["CWE-89"]
    assert sqli.owasp == ["owasp2021-a03-injection"]
    # No CWE/OWASP tags -> empty lists, never None.
    plain = next(f for f in findings if f.rule_id == "java:S1541")
    assert plain.cwe == [] and plain.owasp == []


def test_title_is_first_line_and_raw_is_preserved():
    _, _, findings = _normalized()
    named = next(f for f in findings if f.rule_id == "python:S100")
    assert named.title == "'do_thing' is a bad name; rename it."
    assert "\n" not in named.title
    sqli = next(f for f in findings if f.rule_id == "java:S2077")
    assert sqli.raw["key"] == "AX1"
    assert sqli.raw["severity"] == "BLOCKER"
    assert sqli.message.startswith("Make sure that no vulnerable SQL")


def test_all_findings_are_sonarqube_with_stable_ids():
    issues, hotspots, findings = _normalized()
    assert len(findings) == len(issues) + len(hotspots)
    assert all(f.tool == "sonarqube" for f in findings)
    # Deterministic: same input twice -> same fingerprints.
    again = normalize_sonar(issues, hotspots)
    assert [f.id for f in findings] == [f.id for f in again]
    assert len({f.id for f in findings}) == len(findings)


def test_empty_input_yields_no_findings():
    assert normalize_sonar([]) == []
    assert normalize_sonar([], []) == []
