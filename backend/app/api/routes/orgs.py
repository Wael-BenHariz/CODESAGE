"""Organization routes — settings (Step 3; invitations arrive in Step 11).

GET /orgs — the caller's org context (Step 5): members see their own
``org_members`` rows, PLATFORM_ADMIN sees every org (F2). Pure read.

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import Org, OrgMember, OrgSetting, User
from app.schemas.org import OrgSummary
from app.schemas.org_settings import (
    EffectiveValues,
    NumericCeilings,
    OrgSettingsResponse,
    OverriddenFlags,
    SettingsValues,
)
from app.security.dependencies import get_current_user
from app.security.org_access import OrgAccess, require_org_role
from app.security.roles import ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN
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


@router.get("", response_model=list[OrgSummary])
async def list_my_orgs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Organizations the caller may act in — the UI's org context (Step 5).

    Members see their own ``org_members`` rows; PLATFORM_ADMIN sees every
    org (F2 read/settings bypass) with ``role`` only where they also hold
    a membership row. Pure read → ``get_current_user`` (any role, NONE
    included — a NONE user simply has no memberships).
    """
    if current_user.role == ROLE_PLATFORM_ADMIN:
        # F2: platform admins may open settings on any org — list them all,
        # enriching with the caller's own membership role when one exists.
        membership_rows = (
            await db.execute(
                select(OrgMember.org_id, OrgMember.role).where(
                    OrgMember.user_id == current_user.id
                )
            )
        ).all()
        memberships = {row.org_id: row.role for row in membership_rows}
        org_rows = (
            await db.execute(
                select(Org.id, Org.name, Org.account_type).order_by(Org.name)
            )
        ).all()
        return [
            OrgSummary(
                id=row.id,
                name=row.name,
                account_type=row.account_type,
                role=memberships.get(row.id),
            )
            for row in org_rows
        ]

    rows = (
        await db.execute(
            select(Org.id, Org.name, Org.account_type, OrgMember.role)
            .join(OrgMember, OrgMember.org_id == Org.id)
            .where(OrgMember.user_id == current_user.id)
            .order_by(Org.name)
        )
    ).all()
    return [
        OrgSummary(
            id=row.id,
            name=row.name,
            account_type=row.account_type,
            role=row.role,
        )
        for row in rows
    ]


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
