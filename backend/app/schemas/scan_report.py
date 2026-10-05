"""Response model for the unified scan-report endpoint."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.services.normalizers import NormalizedFinding, ToolFailure


class ScanReportResponse(BaseModel):
    """One review's latest static-analysis scan (migration 010 tables).

    ``summary`` always describes the FULL scan; ``findings`` may be
    filtered by the endpoint's ``tool`` / ``severity`` query params.
    """

    scan_id: str
    review_id: str
    tools_run: list[str]
    tools_failed: list[ToolFailure]
    summary: dict[str, Any]
    findings: list[NormalizedFinding]
    created_at: datetime
