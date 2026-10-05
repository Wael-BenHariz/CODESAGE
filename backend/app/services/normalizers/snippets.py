"""Snippet enrichment: give every finding ±N lines of real source context.

Semgrep snippets are a single matched line and SonarQube findings carry no
snippet at all — neither is enough for an agent (or a human) to *validate*
the finding. ``enrich_snippets`` rewrites ``finding.snippet`` from the
worker's fetched workspace (the same ``[{"filename", "content"}]`` list both
analyzers scanned), including the lines around it.

Lines are rendered as ``<lineno>: <text>`` so the excerpt can be mapped
back to the file without counting. Findings that can't be enriched keep
their existing snippet: file-level findings (no line), files missing from
the workspace (e.g. binary/skipped), or lines past EOF.
"""

from app.services.normalizers.schema import NormalizedFinding

# Lines of context on each side of the finding (brief: ±10 lines).
DEFAULT_CONTEXT_LINES = 10


def enrich_snippets(
    findings: list[NormalizedFinding],
    files: list[dict],
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> int:
    """Fill/replace ``finding.snippet`` with ±``context_lines`` of source.

    Mutates the findings in place (they're freshly normalized per scan).
    Returns how many findings were enriched.
    """
    workspace: dict[str, list[str]] = {}
    for file in files:
        name = str(file.get("filename") or "").strip()
        content = file.get("content")
        if name and isinstance(content, str):
            workspace[name] = content.splitlines()

    enriched = 0
    for finding in findings:
        lines = workspace.get(finding.file_path)
        if not lines or finding.line_start is None:
            continue
        total = len(lines)
        if not 1 <= finding.line_start <= total:
            continue  # file-level or past EOF — keep whatever snippet exists

        end_line = finding.line_end or finding.line_start
        end_line = max(min(end_line, total), finding.line_start)
        start_line = max(1, finding.line_start - context_lines)
        stop = min(total, end_line + context_lines)
        finding.snippet = "\n".join(
            f"{n}: {lines[n - 1]}" for n in range(start_line, stop + 1)
        )
        enriched += 1
    return enriched
