"""Invitation routes (plan Step 11).

Two halves:

**Org-nested** (``org_router``, mounted under ``/orgs``) — guarded by
``require_org_role``:

- ``POST   /orgs/{org_id}/invitations``            member + ≥ ORG_ADMIN.
  Mutating action → **no PLATFORM_ADMIN bypass** (F2: only reads and
  settings bypass membership); role restricted to DEVELOPER/REVIEWER by
  the schema (422 otherwise); Redis sliding-window rate limit 20/hour/org
  → 429.
- ``GET    /orgs/{org_id}/invitations``            member + ≥ ORG_ADMIN
  or PLATFORM_ADMIN (plan: "List + revoke: ORG_ADMIN … or PLATFORM_ADMIN").
- ``DELETE /orgs/{org_id}/invitations/{id}`        same floor as list;
  cross-org and unknown ids share one 404. Already-accepted → 409.

**Token-keyed** (``router``, mounted under ``/invitations``):

- ``GET  /invitations/{token}``                    **public** (route
  inventory allow-listed): pending + unexpired → ``{org_name, role,
  email_masked}``; invalid, expired, revoked or already-used all return
  the *same* 404 — a caller must not learn whether a token ever existed.
- ``POST /invitations/{token}/accept``             authenticated (any
  role, NONE included): hash lookup + lock; used → 409, expired/revoked →
  410; **one transaction** — conditional ``UPDATE … WHERE status='pending'``
  (rowcount 0 → 409: single-use, double-click safe) then the membership
  upsert that never downgrades (ORG_ADMIN stays ORG_ADMIN). Email mismatch
  is allowed, warned, and reported as ``email_mismatch``.

The raw token is created here, hashed for storage, and travels only in
the emailed link — it never appears in a response or an app log.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.models import Org, OrgInvitation, OrgMember, User
from app.schemas.invitation import (
    InvitationAcceptResult,
    InvitationCreate,
    InvitationOut,
    InvitationPreview,
)
from app.security.dependencies import get_current_user
from app.security.org_access import OrgAccess, require_org_role
from app.security.roles import ROLE_ORG_ADMIN
from app.services import invite_rate_limit, mail

logger = logging.getLogger(__name__)

org_router = APIRouter()  # mounted with prefix /orgs
router = APIRouter()  # mounted with prefix /invitations

_INVITE_TTL_DAYS = 7
_INVITATION_NOT_FOUND = "Invitation not found"

# Guards (plan §3 endpoint table + the "List + revoke … or PLATFORM_ADMIN"
# line): create needs membership (no F2 bypass — it is a mutation of a
# customer's org); list/revoke also admit PLATFORM_ADMIN.
_inviter = require_org_role(ROLE_ORG_ADMIN, write=True, platform_admin_bypass=False)
_invitation_admin = require_org_role(
    ROLE_ORG_ADMIN, write=True, platform_admin_bypass=True
)
_invitation_reader = require_org_role(
    ROLE_ORG_ADMIN, write=False, platform_admin_bypass=True
)


def _not_found() -> HTTPException:
    """One 404 detail for invalid/expired/revoked/used — no enumeration."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=_INVITATION_NOT_FOUND
    )


def _hash_token(token: str) -> str:
    """SHA-256 hex of the raw token — the only form stored in the DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _mask_email(email: str) -> str:
    """``john@example.com`` → ``jo***@example.com`` (plan's masking shape)."""
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    return f"{local[:2]}***@{domain}"


def _to_out(invitation: OrgInvitation, inviter_login: str | None) -> InvitationOut:
    """Serialize without ever exposing ``token_hash``."""
    return InvitationOut(
        id=UUID(str(invitation.id)),
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invited_by=inviter_login,
    )


async def _load_open_invitation(db: AsyncSession, token: str) -> OrgInvitation:
    """Hash-lookup a *usable* invitation or raise the uniform 404.

    Deliberately hashes whatever string arrives (no UUID parse): a
    malformed token behaves exactly like an unknown one.
    """
    result = await db.execute(
        select(OrgInvitation).where(OrgInvitation.token_hash == _hash_token(token))
    )
    invitation = result.scalar_one_or_none()
    if invitation is None or invitation.status != "pending":
        raise _not_found()
    if invitation.expires_at <= datetime.now(timezone.utc):
        raise _not_found()
    return invitation


# --- org-nested: create / list / revoke --------------------------------------


@org_router.post(
    "/{org_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    payload: InvitationCreate,
    access: Annotated[OrgAccess, Depends(_inviter)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Invite a teammate as DEVELOPER/REVIEWER (20/hour/org → 429).

    The raw token exists only in the emailed link; the row stores its
    SHA-256 hash. Mail failures never fail the invitation (the row is
    already committed) — ``send_invitation_email`` logs them.
    """
    org = access.org
    if not await invite_rate_limit.allow_invitation(str(org.id)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Invitation rate limit reached (20 per hour per org).",
        )

    token = secrets.token_urlsafe(32)
    invitation = OrgInvitation(
        org_id=org.id,
        email=payload.email.strip(),
        role=payload.role,
        token_hash=_hash_token(token),
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(days=_INVITE_TTL_DAYS),
        invited_by=access.user.id,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    # Audit without the token; the raw link only travels via the mail
    # sender (ConsoleMailSender logs it in dev — by design, plan §Mail).
    logger.info(
        "invitation_created org_id=%s actor=%s email=%s role=%s expires_at=%s",
        org.id,
        access.user.login,
        invitation.email,
        invitation.role,
        invitation.expires_at.isoformat(),
    )
    mail.send_invitation_email(
        to=invitation.email,
        org_name=org.name,
        role=invitation.role,
        invite_url=f"{settings.FRONTEND_URL.rstrip('/')}/invite/accept?token={token}",
    )
    return _to_out(invitation, access.user.login)


@org_router.get("/{org_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(
    access: Annotated[OrgAccess, Depends(_invitation_reader)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Every invitation for the org, newest first — status included so the
    UI can filter the pending ones itself."""
    rows = (
        await db.execute(
            select(OrgInvitation, User.login)
            .join(User, User.id == OrgInvitation.invited_by)
            .where(OrgInvitation.org_id == access.org.id)
            .order_by(OrgInvitation.created_at.desc())
        )
    ).all()
    return [_to_out(invitation, login) for invitation, login in rows]


@org_router.delete(
    "/{org_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: UUID,
    access: Annotated[OrgAccess, Depends(_invitation_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Revoke a pending invitation (idempotent once revoked/expired).

    Scoping by ``access.org.id`` makes cross-org and unknown ids the same
    404. Accepted invitations are already memberships → 409 (remove the
    member instead; revocation never silently drops an access grant).
    """
    result = await db.execute(
        select(OrgInvitation).where(
            OrgInvitation.id == invitation_id,
            OrgInvitation.org_id == access.org.id,
        )
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise _not_found()
    if invitation.status == "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation already accepted — remove the member instead.",
        )
    if invitation.status == "pending":
        invitation.status = "revoked"
        await db.commit()
        logger.info(
            "invitation_revoked org_id=%s invitation_id=%s actor=%s",
            access.org.id,
            invitation.id,
            access.user.login,
        )
    # already revoked/expired → idempotent 204


# --- token-keyed: public preview + authenticated accept ----------------------


@router.get("/{token}", response_model=InvitationPreview)
async def preview_invitation(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """What the link offers: org name, invitable role, masked address.

    Public by necessity (the invitee has no session yet); every
    non-usable state maps to the identical 404 so tokens and addresses
    cannot be enumerated.
    """
    invitation = await _load_open_invitation(db, token)
    org_row = (
        await db.execute(select(Org).where(Org.id == invitation.org_id))
    ).scalar_one_or_none()
    if org_row is None:
        raise _not_found()
    return InvitationPreview(
        org_name=org_row.name,
        role=invitation.role,
        email_masked=_mask_email(invitation.email),
    )


@router.post("/{token}/accept", response_model=InvitationAcceptResult)
async def accept_invitation(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Join the org — authenticated (any role, NONE included): the new
    membership row grants access, not the token.

    One transaction: the row is locked, expiry/used/revoked are checked
    (409 used / 410 expired or revoked), then a conditional
    ``UPDATE … WHERE status='pending'`` flips the invitation to accepted
    (rowcount 0 → 409 — single-use and double-click safe) and the
    membership upsert never downgrades an existing role.
    """
    result = await db.execute(
        select(OrgInvitation)
        .where(OrgInvitation.token_hash == _hash_token(token))
        .with_for_update()
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise _not_found()
    if invitation.status == "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Invitation already used"
        )
    if invitation.status in ("revoked", "expired"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Invitation no longer valid"
        )
    if invitation.expires_at <= datetime.now(timezone.utc):
        invitation.status = "expired"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Invitation no longer valid"
        )

    # Single-use guard — only flip while still pending.
    flipped = cast(
        "CursorResult[Any]",
        await db.execute(
            update(OrgInvitation)
            .where(
                OrgInvitation.id == invitation.id,
                OrgInvitation.status == "pending",
            )
            .values(status="accepted")
        ),
    )
    if flipped.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Invitation already used"
        )

    # Membership upsert — never downgrade: ORG_ADMIN stays ORG_ADMIN and
    # REVIEWER stays REVIEWER when the invitation only grants DEVELOPER
    # (plan: "GREATEST-ish CASE"). org_members roles are exactly
    # DEVELOPER/REVIEWER/ORG_ADMIN (Q1), so three cases are exhaustive.
    invite_role = invitation.role
    await db.execute(
        pg_insert(OrgMember)
        .values(
            org_id=invitation.org_id,
            user_id=current_user.id,
            role=invite_role,
        )
        .on_conflict_do_update(
            index_elements=["org_id", "user_id"],
            set_={
                "role": case(
                    (OrgMember.role == "ORG_ADMIN", "ORG_ADMIN"),
                    (OrgMember.role == "REVIEWER", "REVIEWER"),
                    else_=invite_role,
                ),
            },
        )
    )
    final_role = (
        await db.execute(
            select(OrgMember.role).where(
                OrgMember.org_id == invitation.org_id,
                OrgMember.user_id == current_user.id,
            )
        )
    ).scalar_one()

    # Email mismatch: allowed — warn and let the UI offer "continue
    # anyway". Compared only when BOTH sides carry an address.
    user_email = (current_user.email or "").strip().lower()
    invite_email = (invitation.email or "").strip().lower()
    mismatch = bool(user_email and invite_email) and user_email != invite_email
    if mismatch:
        logger.warning(
            "invitation_email_mismatch org_id=%s invite_email=%s "
            "user_email=%s user_id=%s",
            invitation.org_id,
            invitation.email,
            current_user.email,
            current_user.id,
        )

    org_row = (
        await db.execute(select(Org).where(Org.id == invitation.org_id))
    ).scalar_one()
    await db.commit()
    logger.info(
        "invitation_accepted org_id=%s user_id=%s role=%s email_mismatch=%s",
        invitation.org_id,
        current_user.id,
        final_role,
        mismatch,
    )
    return InvitationAcceptResult(
        org_id=UUID(str(org_row.id)),
        org_name=org_row.name,
        role=final_role,
        email_mismatch=mismatch,
    )
