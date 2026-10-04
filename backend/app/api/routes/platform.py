"""Platform-wide settings routes (Step 3) — PLATFORM_ADMIN only.

GET/PUT /platform/settings: per-field platform **defaults** and
**ceilings** for the three numeric settings. Ceilings can never exceed
the in-code ``HARD_CAPS`` (422), and a default above its (final) ceiling
is rejected too (422) — the same rule org PUTs follow.

Null semantics mirror org PUTs: within an (present) block, absent field =
keep, explicit null = reset (default → config/code value, ceiling →
hard cap). Audit = structured log with per-field ``{old, new}``.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import PlatformSetting, User
from app.schemas.org_settings import (
    EffectiveValues,
    NumericCeilings,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    SettingsValues,
)
from app.security.roles import require_super_admin
from app.services import org_settings as settings_service

logger = logging.getLogger(__name__)
router = APIRouter()

# starlette >= 1.x renamed HTTP_422_UNPROCESSABLE_ENTITY (accessing the old
# name emits a deprecation warning on every call); 422 for older versions.
_UNPROCESSABLE_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


def _hard_caps() -> NumericCeilings:
    return NumericCeilings(**settings_service.HARD_CAPS)


async def _response(
    db: AsyncSession,
    platform_row: PlatformSetting | None,
) -> PlatformSettingsResponse:
    effective = settings_service.merge_settings(None, platform_row)
    return PlatformSettingsResponse(
        defaults=SettingsValues(
            **{
                field: getattr(platform_row, field) if platform_row else None
                for field in settings_service.SETTINGS_FIELDS
            }
        ),
        effective_defaults=EffectiveValues(
            **{
                field: getattr(effective, field)
                for field in settings_service.SETTINGS_FIELDS
            }
        ),
        ceilings=NumericCeilings(**settings_service.platform_ceilings(platform_row)),
        hard_caps=_hard_caps(),
    )


@router.get("/settings", response_model=PlatformSettingsResponse)
async def get_platform_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_super_admin)],
):
    """Stored defaults/ceilings + resolved effective values + hard caps."""
    platform_row = await settings_service.get_platform_setting(db)
    return await _response(db, platform_row)


@router.put("/settings", response_model=PlatformSettingsResponse)
async def update_platform_settings(
    body: PlatformSettingsUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_super_admin)],
):
    """Partial update of platform defaults and ceilings (both optional).

    Validation order (all 422, before persistence): ceilings must sit
    below the hard caps; then every submitted default must fit its final
    ceiling and pass the shared vocabulary checks.
    """
    platform_row = await settings_service.get_platform_setting(db)
    if platform_row is None:
        platform_row = PlatformSetting()
        db.add(platform_row)

    changes: dict[str, dict] = {}

    # 1) Ceilings first — defaults are validated against the FINAL values.
    ceiling_updates: dict = {}
    if body.ceilings is not None:
        for field in body.ceilings.model_fields_set:
            value = getattr(body.ceilings, field)
            if (
                value is not None
                and not 1 <= value <= settings_service.HARD_CAPS[field]
            ):
                raise HTTPException(
                    status_code=_UNPROCESSABLE_422,
                    detail=(
                        f"ceiling_{field} must be between 1 and "
                        f"{settings_service.HARD_CAPS[field]} (hard cap)"
                    ),
                )
            ceiling_updates[f"ceiling_{field}"] = value

    final_ceilings = dict(settings_service.platform_ceilings(platform_row))
    for field in settings_service.NUMERIC_FIELDS:
        ceiling_value = ceiling_updates.get(f"ceiling_{field}", "__absent__")
        if ceiling_value == "__absent__":
            continue
        # None (explicit null) = reset to the hard cap.
        final_ceilings[field] = (
            settings_service.HARD_CAPS[field]
            if ceiling_value is None
            else int(ceiling_value)
        )

    # 2) Defaults against the final ceilings + shared vocabulary checks.
    default_updates: dict = {}
    if body.defaults is not None:
        default_updates = {
            field: getattr(body.defaults, field)
            for field in body.defaults.model_fields_set
        }
        try:
            settings_service.validate_all(default_updates, final_ceilings)
        except ValueError as exc:
            raise HTTPException(
                status_code=_UNPROCESSABLE_422,
                detail=str(exc),
            ) from exc

    # 3) Apply (null = reset to config/code default, i.e. store NULL).
    for column, value in {**ceiling_updates, **default_updates}.items():
        old_value = getattr(platform_row, column)
        if old_value != value:
            changes[column] = {"old": old_value, "new": value}
        setattr(platform_row, column, value)

    await db.commit()

    logger.info(
        "platform_settings_updated actor_id=%s actor_login=%s changes=%s",
        current_user.id,
        current_user.login,
        changes,
    )
    return await _response(db, platform_row)
