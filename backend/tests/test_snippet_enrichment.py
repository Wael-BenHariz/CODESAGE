"""enrich_snippets: ±10 lines of numbered source for every findable line.

The agent prompts (and the scan-report API) rely on snippets being enough
to *validate* a finding without re-reading the whole file.
"""

from app.services.normalizers import enrich_snippets
from app.services.normalizers.schema import NormalizedFinding
from app.services.normalizers.snippets import DEFAULT_CONTEXT_LINES


def _finding(
    *,
    file_path: str = "src/a.py",
    line_start: int | None = 10,
    line_end: int | None = None,
    snippet: str | None = None,
    tool: str = "sonarqube",
) -> NormalizedFinding:
    return NormalizedFinding(
        tool=tool,  # type: ignore[arg-type]
        rule_id="r1",
        message="problem",
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        snippet=snippet,
    )


def _files(n_lines: int = 100, filename: str = "src/a.py") -> list[dict]:
    return [
        {
            "filename": filename,
            "content": "\n".join(f"L{i}" for i in range(1, n_lines + 1)),
        }
    ]


def test_default_context_is_ten_lines():
    assert DEFAULT_CONTEXT_LINES == 10


def test_fills_sonar_finding_with_plus_minus_10_numbered_lines():
    finding = _finding(line_start=50, line_end=51)

    assert enrich_snippets([finding], _files()) == 1

    lines = finding.snippet.splitlines()
    # 50-10=40 .. 51+10=61, each prefixed with its line number.
    assert lines[0] == "40: L40"
    assert lines[-1] == "61: L61"
    assert len(lines) == 22


def test_replaces_semgrep_single_line_snippet():
    finding = _finding(line_start=10, snippet="eval(payload)", tool="semgrep")

    enrich_snippets([finding], _files())

    assert finding.snippet.startswith("1: L1")  # 10-10 clamped to 1
    assert finding.snippet.endswith("20: L20")  # line_end None -> 10+10


def test_file_level_finding_keeps_its_snippet():
    finding = _finding(line_start=None, snippet="file-level note")

    assert enrich_snippets([finding], _files()) == 0
    assert finding.snippet == "file-level note"


def test_missing_file_keeps_existing_snippet():
    finding = _finding(file_path="other/absent.py", snippet="keep me")

    assert enrich_snippets([finding], _files()) == 0
    assert finding.snippet == "keep me"


def test_line_past_eof_keeps_existing_snippet():
    finding = _finding(line_start=10, snippet="keep me")  # file has 1 line
    files = [{"filename": "src/a.py", "content": "only line\n"}]

    assert enrich_snippets([finding], files) == 0
    assert finding.snippet == "keep me"


def test_enrichment_counts_only_what_it_changed():
    files = _files(n_lines=30)
    in_file = _finding(line_start=10)
    absent = _finding(file_path="nope.py", line_start=10, snippet="x")
    file_level = _finding(line_start=None)

    assert enrich_snippets([in_file, absent, file_level], files) == 1
    assert in_file.snippet is not None and absent.snippet == "x"


def test_line_numbers_beyond_workspace_match_by_filename_only():
    # A differently-named file must not satisfy the lookup.
    finding = _finding(file_path="src/b.py", line_start=10)

    assert enrich_snippets([finding], _files(filename="src/a.py")) == 0
    assert finding.snippet is None
