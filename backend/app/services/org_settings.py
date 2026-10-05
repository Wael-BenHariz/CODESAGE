"""Effective organization settings — the *only* merge point (plan Step 3).

Merge chain per field, strongest first:

    org override  →  platform default  →  config/code default

Numeric fields are additionally **clamped to the platform ceiling on
read** (defense in depth — even a hand-edited org row above its ceiling
serves the ceiling). Ceilings themselves never exceed ``HARD_CAPS``.

``resolve_org_settings(db, org_id)`` is what the worker (Step 4) and the
settings endpoints consume; ``merge_settings`` is the pure core so tests
exercise the chain without a database.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.db.models import OrgSetting, PlatformSetting
from app.services.agents.specialist_agents import MAX_FINDINGS_PER_AGENT
from app.services.review_orchestrator import AGENT_DOMAINS

logger = logging.getLogger(__name__)

# --- vocabulary --------------------------------------------------------------

NUMERIC_FIELDS = ("diff_char_cap", "max_findings_per_agent", "max_concurrent_reviews")

# Unraisable in-code caps. ``diff_char_cap`` mirrors
# ``app.workers.review_processor.DIFF_MAX_CHARS`` (same value, pinned by
# test_org_settings.py::test_hard_caps_match_worker_constants).
HARD_CAPS: dict[str, int] = {
    "diff_char_cap": 100_000,
    "max_findings_per_agent": 100,
    "max_concurrent_reviews": 50,
}

TRIGGER_VOCAB = ("pull_request", "manual")
SEVERITY_VOCAB = ("info", "low", "medium", "high", "critical")
POSTING_MODE_VOCAB = ("auto", "staged")

# Field order = response/reporting order.
SETTINGS_FIELDS = (
    "diff_char_cap",
    "max_findings_per_agent",
    "max_concurrent_reviews",
    "enabled_agents",
    "sonarqube_enabled",
    "semgrep_enabled",
    "review_triggers",
    "min_severity_to_post",
    "posting_mode",
    "ai_model",
)


def config_defaults() -> dict:
    """Config/code defaults — the last link of the merge chain.

    Kept as a function (not a module constant) so env changes in tests are
    picked up per call.
    """
    return {
        "diff_char_cap": app_settings.LLM_DIFF_CHAR_CAP,
        "max_findings_per_agent": MAX_FINDINGS_PER_AGENT,
        "max_concurrent_reviews": app_settings.BULLMQ_CONCURRENCY,
        "enabled_agents": list(AGENT_DOMAINS),
        "sonarqube_enabled": True,
        "semgrep_enabled": app_settings.SEMGREP_ENABLED,
        "review_triggers": list(TRIGGER_VOCAB),
        "min_severity_to_post": "info",
        "posting_mode": "auto",
        "ai_model": None,
    }


def platform_ceilings(platform_row: PlatformSetting | None) -> dict[str, int]:
    """Effective ceilings: stored platform ceiling, else the hard cap."""
    ceilings = {}
    for field in NUMERIC_FIELDS:
        stored = (
            getattr(platform_row, f"ceiling_{field}", None) if platform_row else None
        )
        ceilings[field] = int(stored) if stored is not None else HARD_CAPS[field]
    return ceilings


@dataclass(frozen=True)
class EffectiveSettings:
    """Fully merged, ceiling-clamped settings for one org (or global)."""

    diff_char_cap: int
    max_findings_per_agent: int
    max_concurrent_reviews: int
    enabled_agents: list
    sonarqube_enabled: bool
    semgrep_enabled: bool
    review_triggers: list
    min_severity_to_post: str
    posting_mode: str
    ai_model: str | None
    overridden: dict  # field -> True when the ORG override (not platform) applies


def merge_settings(
    org_row: OrgSetting | None,
    platform_row: PlatformSetting | None,
) -> EffectiveSettings:
    """Pure merge: org override → platform default → config default.

    Numeric results are clamped to the effective ceiling on read.
    """
    defaults = config_defaults()
    ceilings = platform_ceilings(platform_row)

    merged: dict = {}
    overridden: dict = {}
    for field in SETTINGS_FIELDS:
        org_value = getattr(org_row, field, None) if org_row is not None else None
        platform_value = (
            getattr(platform_row, field, None) if platform_row is not None else None
        )
        if org_value is not None:
            value, from_org = org_value, True
        elif platform_value is not None:
            value, from_org = platform_value, False
        else:
            value, from_org = defaults[field], False

        if field in NUMERIC_FIELDS:
            value = min(int(value), ceilings[field])
        elif field in ("enabled_agents", "review_triggers"):
            value = list(value)  # copy: never alias the stored JSONB list

        merged[field] = value
        overridden[field] = from_org

    return EffectiveSettings(**merged, overridden=overridden)


# --- persistence helpers -----------------------------------------------------


async def get_platform_setting(db: AsyncSession) -> PlatformSetting | None:
    result = await db.execute(select(PlatformSetting).limit(1))
    return result.scalar_one_or_none()


async def get_org_setting(db: AsyncSession, org_id: UUID) -> OrgSetting | None:
    result = await db.execute(select(OrgSetting).where(OrgSetting.org_id == org_id))
    return result.scalar_one_or_none()


async def resolve_org_settings(
    db: AsyncSession,
    org_id: UUID | None,
) -> EffectiveSettings:
    """The worker's entry point: effective settings for ``org_id``.

    ``org_id=None`` (no resolvable org for a review) yields the global
    defaults (platform row still applies — it is org-independent).
    """
    platform_row = await get_platform_setting(db)
    org_row = await get_org_setting(db, org_id) if org_id is not None else None
    return merge_settings(org_row, platform_row)


# --- validation (routes translate ValueError -> 422) -------------------------


def validate_setting_field(field: str, value, ceilings: dict[str, int]) -> None:
    """Validate one PUT value against vocabulary and ceilings.

    ``value is None`` is always valid (explicit null = reset to default).
    Raises ``ValueError`` with a client-safe message on violation.
    """
    if value is None:
        return

    if field in NUMERIC_FIELDS:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{field} must be an integer")
        if value < 1:
            raise ValueError(f"{field} must be at least 1")
        if value > ceilings[field]:
            raise ValueError(
                f"{field} exceeds the ceiling: {value} > {ceilings[field]}"
            )
    elif field == "enabled_agents":
        unknown = [a for a in value if a not in AGENT_DOMAINS]
        if unknown:
            raise ValueError(
                f"Unknown agent(s) {unknown}; allowed: {list(AGENT_DOMAINS)}"
            )
    elif field == "review_triggers":
        unknown = [t for t in value if t not in TRIGGER_VOCAB]
        if unknown:
            raise ValueError(
                f"Unknown trigger(s) {unknown}; allowed: {list(TRIGGER_VOCAB)}"
            )
    elif field == "min_severity_to_post":
        if value not in SEVERITY_VOCAB:
            raise ValueError(
                f"min_severity_to_post must be one of {list(SEVERITY_VOCAB)}"
            )
    elif field == "posting_mode":
        if value not in POSTING_MODE_VOCAB:
            raise ValueError(f"posting_mode must be one of {list(POSTING_MODE_VOCAB)}")
    elif field == "ai_model":
        if not str(value).strip():
            raise ValueError("ai_model must be a non-empty string (or null to reset)")


def validate_all(values: dict, ceilings: dict[str, int]) -> None:
    """Validate a {field: value} mapping (only the keys present)."""
    for field, value in values.items():
        validate_setting_field(field, value, ceilings)
