"""Org & platform settings request/response schemas (Step 3).

Value semantics (hard constraint): in a PUT body, an **absent** field
means "keep the stored value" and an **explicit null** means "reset to
the default" — ``model_fields_set`` distinguishes the two. Type/shape
validation lives here (FastAPI → 422); vocabulary and ceiling checks run
in the route against the live platform ceilings (also 422, uniform
``detail`` message).

Responses carry four blocks: stored overrides, effective (merged and
ceiling-clamped) values, the numeric ceilings, and per-field
``overridden`` flags (True when the *org* override is the active link of
the merge chain).
"""

from uuid import UUID

from pydantic import BaseModel


class SettingsValues(BaseModel):
    """All ten settings, every one optional/nullable.

    Used as org overrides, as stored platform defaults, and as the PUT
    body for org settings (absent = keep, null = reset).
    """

    diff_char_cap: int | None = None
    max_findings_per_agent: int | None = None
    max_concurrent_reviews: int | None = None
    enabled_agents: list[str] | None = None
    sonarqube_enabled: bool | None = None
    semgrep_enabled: bool | None = None
    review_triggers: list[str] | None = None
    min_severity_to_post: str | None = None
    posting_mode: str | None = None
    ai_model: str | None = None


class EffectiveValues(BaseModel):
    """Merged values — numerics/lists/bools/enums always present."""

    diff_char_cap: int
    max_findings_per_agent: int
    max_concurrent_reviews: int
    enabled_agents: list[str]
    sonarqube_enabled: bool
    semgrep_enabled: bool
    review_triggers: list[str]
    min_severity_to_post: str
    posting_mode: str
    ai_model: str | None = None


class NumericCeilings(BaseModel):
    """The three numeric ceilings (org overrides are clamped/rejected at these)."""

    diff_char_cap: int
    max_findings_per_agent: int
    max_concurrent_reviews: int


class OverriddenFlags(BaseModel):
    """Per-field: True when the org override (not platform/config) is active."""

    diff_char_cap: bool
    max_findings_per_agent: bool
    max_concurrent_reviews: bool
    enabled_agents: bool
    sonarqube_enabled: bool
    semgrep_enabled: bool
    review_triggers: bool
    min_severity_to_post: bool
    posting_mode: bool
    ai_model: bool


class OrgSettingsResponse(BaseModel):
    """GET/PUT /orgs/{org_id}/settings."""

    org_id: UUID
    overrides: SettingsValues  # stored (NULL = inherit platform/config)
    effective: EffectiveValues  # merged + ceiling-clamped
    ceilings: NumericCeilings
    overridden: OverriddenFlags


class CeilingsUpdate(BaseModel):
    """Platform ceiling overrides (null = reset to the hard cap)."""

    diff_char_cap: int | None = None
    max_findings_per_agent: int | None = None
    max_concurrent_reviews: int | None = None


class PlatformSettingsUpdate(BaseModel):
    """PUT /platform/settings — two optional blocks, both partial.

    Absent block = keep everything in it; within a block, absent field =
    keep, explicit null = reset (defaults → config/code default,
    ceilings → hard cap).
    """

    defaults: SettingsValues | None = None
    ceilings: CeilingsUpdate | None = None


class PlatformSettingsResponse(BaseModel):
    """GET/PUT /platform/settings."""

    defaults: SettingsValues  # stored (NULL = config/code default wins)
    effective_defaults: EffectiveValues  # stored merged with config/code
    ceilings: NumericCeilings  # stored, falling back to hard caps
    hard_caps: NumericCeilings  # unraisable in-code maximums
