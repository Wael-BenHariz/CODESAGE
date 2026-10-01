"""Tool-agnostic finding schema shared by every static analyzer.

SonarQube and Semgrep speak different dialects; everything downstream —
dedup, persistence, the review API, and the specialist agents — consumes
only these models. Part of the Semgrep integration (plan:
``docs/SEMGREP_INTEGRATION_PLAN.md``).
"""

from app.services.normalizers.schema import (
    NormalizedFinding,
    ScanReport,
    Severity,
    Tool,
    ToolFailure,
    fingerprint,
)
from app.services.normalizers.sonarqube import normalize_sonar

__all__ = [
    "NormalizedFinding",
    "ScanReport",
    "Severity",
    "Tool",
    "ToolFailure",
    "fingerprint",
    "normalize_sonar",
]
