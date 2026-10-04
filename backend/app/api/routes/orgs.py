"""Organization routes — settings (Step 3; invitations arrive in Step 11).

GET/PUT /orgs/{org_id}/settings — guard: member + effective role
≥ ORG_ADMIN (capability model in ``app.security.org_access``; cross-org →
404, DEVELOPER member → 403, NONE write → 403, PLATFORM_ADMIN ok per F2).

PUT semantics: partial body — absent field = keep, explicit null = reset.
Any numeric above its ceiling, unknown agent/trigger/enum or a blank
model → 422 (before persistence). Audit = structured log with per-field
``{old, new}`` (no secrets exist in these settings).
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import OrgSetting
from app.schemas.org_settings import (
    EffectiveValues,
    NumericCeilings,
    OrgSettingsResponse,
    OverriddenFlags,
    SettingsValues,
)
from app.security.org_access import OrgAccess, require_org_role
from app.security.roles import ROLE_ORG_ADMIN
from app.services import org_settings as settings_service

logger = logging.getLogger(__name__)
router = APIRouter()

# starlette >= 1.x renamed HTTP_422_UNPROCESSABLE_ENTITY (accessing the old
# name emits a deprecation warning on every call); 422 for older versions.
_UNPROCESSABLE_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

# Step 3 endpoints are settings endpoints → PLATFORM_ADMIN may bypass
# membership without an org row (flag F2 carve-out, reads and settings).
_settings_reader = require_org_role(ROLE_ORG_ADMIN, write=False)
_settings_writer = require_org_role(ROLE_ORG_ADMIN, write=True)


async def _response(
    db: AsyncSession,
    org_id: UUID,
) -> OrgSettingsResponse:
    """Build the four-block response for one org."""
    org_row = await settings_service.get_org_setting(db, org_id)
    platform_row = await settings_service.get_platform_setting(db)
    effective = settings_service.merge_settings(org_row, platform_row)
    return OrgSettingsResponse(
        org_id=org_id,
        overrides=SettingsValues(
            **{
                field: getattr(org_row, field) if org_row is not None else None
                for field in settings_service.SETTINGS_FIELDS
            }
        ),
        effective=EffectiveValues(
            **{
                field: getattr(effective, field)
                for field in settings_service.SETTINGS_FIELDS
            }
        ),
        ceilings=NumericCeilings(**settings_service.platform_ceilings(platform_row)),
        overridden=OverriddenFlags(**effective.overridden),
    )


@router.get("/{org_id}/settings", response_model=OrgSettingsResponse)
async def get_org_settings(
    org_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _access: Annotated[OrgAccess, Depends(_settings_reader)],
):
    """Stored overrides + effective values + ceilings + overridden flags."""
    return await _response(db, org_id)


@router.put("/{org_id}/settings", response_model=OrgSettingsResponse)
async def update_org_settings(
    org_id: UUID,
    body: SettingsValues,
    db: Annotated[AsyncSession, Depends(get_db)],
    access: Annotated[OrgAccess, Depends(_settings_writer)],
):
    """Partial update: absent field = keep, explicit null = reset.

    Ceiling/vocabulary violations are rejected with 422 **before** any
    write. Only fields present in the body are touched.
    """
    platform_row = await settings_service.get_platform_setting(db)
    ceilings = settings_service.platform_ceilings(platform_row)

    submitted = {field: getattr(body, field) for field in body.model_fields_set}
    try:
        settings_service.validate_all(submitted, ceilings)
    except ValueError as exc:
        raise HTTPException(
            status_code=_UNPROCESSABLE_422,
            detail=str(exc),
        ) from exc

    org_row = await settings_service.get_org_setting(db, org_id)
    if org_row is None:
        org_row = OrgSetting(org_id=org_id)
        db.add(org_row)

    changes: dict[str, dict] = {}
    for field, new_value in submitted.items():
        if field == "ai_model" and isinstance(new_value, str):
            new_value = new_value.strip()
        old_value = getattr(org_row, field)
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}
        setattr(org_row, field, new_value)

    await db.commit()

    # Audit = structured log (no audit table exists): actor + org + the
    # exact per-field delta. These settings contain no secrets.
    logger.info(
        "org_settings_updated actor_id=%s actor_login=%s org_id=%s changes=%s",
        access.user.id,
        access.user.login,
        org_id,
        changes,
    )
    return await _response(db, org_id)
