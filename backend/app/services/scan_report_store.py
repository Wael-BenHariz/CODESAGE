"""Read/write helpers for the unified scan report tables (migration 010).

``persist_scan_report`` writes one header row + one row per normalized
finding in a single transaction. It RAISES on failure — the worker wraps
it in its own try/except + rollback so a report insert can never fail a
review (plan: "best-effort, a report insert failure must never fail a
review").

``finding_from_row`` is the inverse mapping used by the review API
(``reference_urls`` -> ``references`` because SQL reserves it).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScanFindingRow, ScanReportRow
from app.services.normalizers import NormalizedFinding, ScanReport

logger = logging.getLogger(__name__)


async def persist_scan_report(
    db: AsyncSession,
    review_id,
    report: ScanReport,
) -> ScanReportRow:
    """Insert the report header + findings rows and commit.

    Raises on any failure — callers decide tolerance (the worker logs and
    rolls back; the review itself continues).
    """
    report_row = ScanReportRow(
        review_id=review_id,
        scan_id=report.scan_id,
        tools_run=report.tools_run,
        tools_failed=[f.model_dump() for f in report.tools_failed],
        summary=report.summary,
    )
    db.add(report_row)
    await db.flush()

    for finding in report.findings:
        db.add(
            ScanFindingRow(
                report_id=report_row.id,
                fingerprint=finding.id,
                tool=finding.tool,
                rule_id=finding.rule_id,
                title=finding.title,
                message=finding.message,
                severity=finding.severity,
                category=finding.category,
                file_path=finding.file_path,
                line_start=finding.line_start,
                line_end=finding.line_end,
                snippet=finding.snippet,
                cwe=finding.cwe or None,
                owasp=finding.owasp or None,
                reference_urls=finding.references or None,
                also_detected_by=finding.also_detected_by or None,
                fix_suggestion=finding.fix_suggestion,
                raw=finding.raw,
            )
        )

    await db.commit()
    return report_row


def finding_from_row(row: ScanFindingRow) -> NormalizedFinding:
    """Map a ``scan_findings`` row back to the unified finding model."""
    return NormalizedFinding(
        id=row.fingerprint,
        tool=row.tool,  # type: ignore[arg-type]
        rule_id=row.rule_id,
        title=row.title,
        message=row.message,
        severity=row.severity,  # type: ignore[arg-type]
        category=row.category,  # type: ignore[arg-type]
        file_path=row.file_path,
        line_start=row.line_start,
        line_end=row.line_end,
        snippet=row.snippet,
        cwe=list(row.cwe or []),
        owasp=list(row.owasp or []),
        references=list(row.reference_urls or []),
        also_detected_by=list(row.also_detected_by or []),
        fix_suggestion=row.fix_suggestion,
        raw=dict(row.raw or {}),
    )
