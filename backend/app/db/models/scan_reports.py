"""Unified static-analysis scan reports (SonarQube + Semgrep findings).

A ``scan_reports`` row is the header of one review scan (which tools ran,
which failed, severity/tool summary); ``scan_findings`` holds one row per
normalized finding with queryable typed columns (tool, severity, ...).
Both are additive — nothing in the existing review tables changes.
"""

from sqlalchemy import ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScanReportRow(Base):
    """Header for one unified static-analysis scan of a review."""

    __tablename__ = "scan_reports"
    __table_args__ = (
        {"comment": "Unified static analysis scan reports (one row per scan)"},
    )

    review_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the review this scan belongs to",
    )

    scan_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Unique scan identifier (uuid)",
    )

    tools_run: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment='Tools that returned results, e.g. ["sonarqube"]',
    )

    tools_failed: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment='Tools that failed: [{"tool": ..., "error": ...}]',
    )

    summary: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="Counts by severity and tool",
    )


class ScanFindingRow(Base):
    """One normalized finding from a static analyzer."""

    __tablename__ = "scan_findings"
    __table_args__ = ({"comment": "Normalized findings from static analyzers"},)

    report_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scan_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the owning scan report",
    )

    fingerprint: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
        comment="Stable sha1 fingerprint (NormalizedFinding.id)",
    )

    tool: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        comment="Producing tool: sonarqube | semgrep",
    )

    rule_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
        comment="Tool-native rule identifier",
    )

    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        default="",
        server_default="",
        comment="Short human-readable title",
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Full finding message",
    )

    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        comment="Unified severity: info|low|medium|high|critical",
    )

    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="best_practice",
        server_default="best_practice",
        comment="bug|vulnerability|code_smell|security_hotspot|best_practice",
    )

    file_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        default="",
        server_default="",
        comment="Repository-relative file path",
    )

    line_start: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="First line (1-based), null for file-level findings",
    )

    line_end: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Last line (1-based), null when not spanning",
    )

    snippet: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Code excerpt around the finding (if captured)",
    )

    cwe: Mapped[list | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="CWE identifiers, e.g. [CWE-89]",
    )

    owasp: Mapped[list | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="OWASP categories/tags",
    )

    # Named reference_urls (not `references` — reserved SQL keyword) to keep
    # the DDL portable; the API maps it back to NormalizedFinding.references.
    reference_urls: Mapped[list | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Reference URLs for the rule/finding",
    )

    fix_suggestion: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Suggested fix, when the tool provides one",
    )

    raw: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="Original tool payload for debugging",
    )
