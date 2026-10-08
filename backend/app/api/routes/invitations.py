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
  email_masked, repositories}``; invalid, expired, revoked or already-used all return
  the *same* 404 — a caller must not learn whether a token ever existed.
- ``POST /invitations/{token}/accept``             authenticated (any
  role, NONE included): hash lookup + lock; used → 409, expired/revoked →
  410; **one transaction** — conditional ``UPDATE … WHERE status='pending'``
  (rowcount 0 → 409: single-use, double-click safe) then the membership
  upsert that never downgrades (ORG_ADMIN stays ORG_ADMIN) plus, when the
  invitation carries ``repository_ids``, the per-repo grants
  (``org_member_repos``) and the ``watched_repos`` rows that turn them
  on. Email mismatch is allowed, warned, and reported as
  ``email_mismatch``.

**Repo-scoped grants** (one role for a whole selection):

- Creation validates every requested repository against the org's GitHub
  App installation (repo → installation → org chain) → 400 before any
  write; only DEVELOPER/REVIEWER can be granted (schema Literal, mirrors
  the 017/019 CHECKs).
- Accept then runs a **best-effort GitHub collaborator pass** (after the
  commit): ``PUT /repos/{owner}/{repo}/collaborators/{login}`` with the
  permission mapped from the role (DEVELOPER → push, REVIEWER → triage).
  Failures are recorded per repo and joined onto
  ``org_invitations.github_error`` — they never fail the accept — and an
  optional outgoing webhook (``INVITATION_WEBHOOK_URL``) is fired last.

The raw token is created here, hashed for storage, and travels only in
the emailed link — it never appears in a response or an app log.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgInvitation,
    OrgMember,
    OrgMemberRepo,
    Repository,
    User,
    WatchedRepo,
)
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
from app.services.github_app import get_installation_token
from app.services.github_collaborator import (
    ROLE_TO_GITHUB_PERMISSION,
    ensure_collaborator,
)

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


def _to_out(
    invitation: OrgInvitation,
    inviter_login: str | None,
    repo_names: dict[UUID, str] | None = None,
) -> InvitationOut:
    """Serialize without ever exposing ``token_hash``.

    ``repo_names`` maps the granted repository ids to their
    ``owner/repo`` full names (resolved by the caller so list/create
    resolve everything in one query); ids whose repository row is gone
    simply have no name to show.
    """
    names = repo_names or {}
    repo_ids = [UUID(str(rid)) for rid in (invitation.repository_ids or [])]
    return InvitationOut(
        id=UUID(str(invitation.id)),
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invited_by=inviter_login,
        repository_ids=repo_ids,
        repositories=[names[rid] for rid in repo_ids if rid in names],
        github_error=invitation.github_error,
    )


async def _repo_names(db: AsyncSession, repo_ids: list[UUID]) -> dict[UUID, str]:
    """``repositories.id`` → ``owner/repo`` for one batch (single query)."""
    if not repo_ids:
        return {}
    rows = (
        await db.execute(
            select(Repository.id, Repository.full_name).where(
                Repository.id.in_(repo_ids)
            )
        )
    ).all()
    return {row.id: row.full_name for row in rows}


async def _org_repositories(
    db: AsyncSession,
    org: Org,
    repo_ids: list[UUID],
) -> tuple[list[Repository], list[UUID]]:
    """Split the requested ids into ``(found, missing)`` for this org.

    A repository belongs to the org exactly when its GitHub App
    installation is the org's (the review authorization chain: repo →
    installation → org). With no installation link nothing can match, so
    any requested id lands in ``missing``. ``missing`` preserves the
    caller's order so the 400 message is stable.
    """
    if not repo_ids:
        return [], []
    rows = (
        (
            await db.execute(
                select(Repository)
                .join(
                    GitHubInstallation,
                    GitHubInstallation.id == Repository.installation_id,
                )
                .where(
                    GitHubInstallation.installation_id == org.installation_id,
                    Repository.id.in_(repo_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    found_ids = {repo.id for repo in rows}
    missing = [rid for rid in repo_ids if rid not in found_ids]
    return list(rows), missing


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


# --- accept-time side effects (GitHub collaborator + outgoing webhook) --------


async def _sync_github_collaborators(
    db: AsyncSession,
    *,
    org: Org,
    invitee: User,
    repos: list[Repository],
    role: str,
) -> dict[UUID, tuple[bool, str | None]]:
    """Best-effort: add the invitee as a GitHub collaborator on each repo.

    Records the outcome per row of ``org_member_repos`` and returns
    ``repo.id → (ok, error)`` so the caller can build the joined summary
    and the webhook payload. **Never raises**: a missing installation, an
    invitee without a GitHub account, or an API failure are just recorded
    — the invitation is already accepted and stays accepted.
    """
    if not repos:
        return {}

    # One shared blocker for every repo (identity first — no token is
    # minted for an invitee the API could never address)…
    blocked: str | None = None
    token: str | None = None
    if org.installation_id is None:
        blocked = "organization has no GitHub App installation"
    elif invitee.github_id is None:
        blocked = "invitee has no GitHub account linked"
    else:
        try:
            token = await get_installation_token(org.installation_id)
        except Exception as exc:  # noqa: BLE001 — best-effort by design
            blocked = f"GitHub installation token unavailable: {exc}"

    permission = ROLE_TO_GITHUB_PERMISSION[role]
    outcomes: dict[UUID, tuple[bool, str | None]] = {}
    for repo in repos:
        ok: bool
        error: str | None
        if blocked is not None:
            ok, error = False, blocked
        else:
            try:
                ok, error = await ensure_collaborator(
                    installation_token=cast(str, token),
                    full_name=repo.full_name,
                    username=invitee.login,
                    permission=permission,
                )
            except Exception as exc:  # noqa: BLE001 — belt and braces
                ok, error = False, f"collaborator add failed: {exc}"
        outcomes[repo.id] = (ok, error)
        await db.execute(
            update(OrgMemberRepo)
            .where(
                OrgMemberRepo.org_id == org.id,
                OrgMemberRepo.user_id == invitee.id,
                OrgMemberRepo.repo_id == repo.id,
            )
            .values(github_collaborator=ok, github_error=error)
        )

    return outcomes


async def _post_json(url: str, payload: dict[str, Any]) -> None:
    """HTTP seam for the outgoing webhook (tests monkeypatch this)."""
    async with httpx.AsyncClient(
        timeout=settings.INVITATION_WEBHOOK_TIMEOUT_SECONDS
    ) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def _fire_accept_webhook(payload: dict[str, Any]) -> None:
    """POST the ``org_invitation.accepted`` event (fire-and-forget).

    Everything is already committed when this runs: a dead consumer, a
    timeout or a 5xx are logged and swallowed — they never change the
    accept response.
    """
    url = settings.INVITATION_WEBHOOK_URL
    if not url:
        return
    try:
        await _post_json(url, payload)
    except Exception as exc:  # noqa: BLE001 — best-effort by design
        logger.warning(
            "invitation webhook failed (best-effort) invitation_id=%s: %s",
            payload.get("invitation_id"),
            exc,
        )


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

    ``repository_ids`` (optional) grants that single role on each of the
    selected repositories: every id is resolved against the org's
    installation first and an unknown one is a 400 **before** anything
    is persisted (an empty selection keeps the original org-only invite).

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

    repo_ids = list(payload.repository_ids)
    if repo_ids:
        _, missing = await _org_repositories(db, org, repo_ids)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Unknown repositories for this organization: "
                    + ", ".join(str(rid) for rid in missing)
                ),
            )

    token = secrets.token_urlsafe(32)
    invitation = OrgInvitation(
        org_id=org.id,
        email=payload.email.strip(),
        role=payload.role,
        repository_ids=repo_ids,
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
        "invitation_created org_id=%s actor=%s email=%s role=%s "
        "repository_ids=%s expires_at=%s",
        org.id,
        access.user.login,
        invitation.email,
        invitation.role,
        [str(rid) for rid in repo_ids],
        invitation.expires_at.isoformat(),
    )
    mail.send_invitation_email(
        to=invitation.email,
        org_name=org.name,
        role=invitation.role,
        invite_url=f"{settings.FRONTEND_URL.rstrip('/')}/invite/accept?token={token}",
    )
    return _to_out(invitation, access.user.login, await _repo_names(db, repo_ids))


@org_router.get("/{org_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(
    access: Annotated[OrgAccess, Depends(_invitation_reader)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Every invitation for the org, newest first — status included so the
    UI can filter the pending ones itself. Repository full names are
    resolved for the whole page in one query."""
    rows = (
        await db.execute(
            select(OrgInvitation, User.login)
            .join(User, User.id == OrgInvitation.invited_by)
            .where(OrgInvitation.org_id == access.org.id)
            .order_by(OrgInvitation.created_at.desc())
        )
    ).all()
    all_ids: list[UUID] = []
    for invitation, _login in rows:
        all_ids.extend(UUID(str(rid)) for rid in (invitation.repository_ids or []))
    names = await _repo_names(db, list(dict.fromkeys(all_ids)))
    return [_to_out(invitation, login, names) for invitation, login in rows]


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
    names = await _repo_names(
        db, [UUID(str(rid)) for rid in (invitation.repository_ids or [])]
    )
    return InvitationPreview(
        org_name=org_row.name,
        role=invitation.role,
        email_masked=_mask_email(invitation.email),
        repositories=[
            names[UUID(str(rid))]
            for rid in (invitation.repository_ids or [])
            if UUID(str(rid)) in names
        ],
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
    (rowcount 0 → 409 — single-use and double-click safe), the
    membership upsert never downgrades an existing role, and — when the
    invitation carries ``repository_ids`` — each repository gets its
    ``org_member_repos`` grant plus the ``watched_repos`` row that turns
    reviews on for it.

    After that commit, two best-effort side effects run (neither can fail
    the accept): the GitHub collaborator pass (per-repo outcomes stored,
    failures joined onto ``github_error``) and the outgoing webhook.
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

    # Repo-scoped grants — SAME transaction as the membership: the
    # invitation's one role on each selected repository plus the
    # watched_repos row that turns reviews on for it. Ids are re-resolved
    # against the org's installation here (ids are stored without an FK):
    # a repository row deleted since creation is logged and skipped.
    requested = [UUID(str(rid)) for rid in (invitation.repository_ids or [])]
    granted_repos, missing = await _org_repositories(db, org_row, requested)
    if missing:
        logger.warning(
            "invitation_repo_missing invitation_id=%s org_id=%s missing=%s",
            invitation.id,
            org_row.id,
            [str(rid) for rid in missing],
        )
    for repo in granted_repos:
        await db.execute(
            pg_insert(OrgMemberRepo)
            .values(
                org_id=invitation.org_id,
                user_id=current_user.id,
                repo_id=repo.id,
                role=invite_role,
                github_collaborator=False,
                github_error=None,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "org_id", "repo_id"],
                set_={
                    "role": invite_role,
                    "github_collaborator": False,
                    "github_error": None,
                    "updated_at": func.now(),
                },
            )
        )
        await db.execute(
            pg_insert(WatchedRepo)
            .values(
                user_id=current_user.id,
                repo_id=repo.github_repo_id,
                repo_name=repo.full_name,
                enabled=True,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "repo_id"])
        )

    await db.commit()
    logger.info(
        "invitation_accepted org_id=%s user_id=%s role=%s email_mismatch=%s "
        "repository_ids=%s",
        invitation.org_id,
        current_user.id,
        final_role,
        mismatch,
        [str(repo.id) for repo in granted_repos],
    )

    # --- after commit: GitHub collaborator pass, then the webhook --------
    outcomes: dict[UUID, tuple[bool, str | None]] = {}
    github_error: str | None = None
    if granted_repos:
        outcomes = await _sync_github_collaborators(
            db, org=org_row, invitee=current_user, repos=granted_repos, role=invite_role
        )
        github_error = (
            "; ".join(
                f"{repo.full_name}: {outcomes[repo.id][1]}"
                for repo in granted_repos
                if not outcomes[repo.id][0]
            )
            or None
        )
        invitation.github_error = github_error
        await db.commit()

    await _fire_accept_webhook(
        {
            "event": "org_invitation.accepted",
            "invitation_id": str(invitation.id),
            "org_id": str(org_row.id),
            "org_name": org_row.name,
            "invited_by": str(invitation.invited_by),
            "invitee": {
                "user_id": str(current_user.id),
                "login": current_user.login,
                "email": invitation.email,
            },
            "role": invite_role,
            "org_role": final_role,
            "email_mismatch": mismatch,
            "repositories": [
                {
                    "id": str(repo.id),
                    "github_repo_id": repo.github_repo_id,
                    "full_name": repo.full_name,
                    "role": invite_role,
                    "github_collaborator": outcomes.get(repo.id, (False, None))[0],
                }
                for repo in granted_repos
            ],
            "github_error": github_error,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    return InvitationAcceptResult(
        org_id=UUID(str(org_row.id)),
        org_name=org_row.name,
        role=final_role,
        email_mismatch=mismatch,
        github_error=github_error,
    )
