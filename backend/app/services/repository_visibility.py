"""Repository read-visibility — the caller's repository *collections*.

Single source of truth for which ``repositories`` rows a caller may SEE
(list, search, fetch by id, list pull requests of). Written for the
repo-scoped-invitation contract (migrations 017/019):

* **personal** — repositories of GitHub App installations the caller's own
  GitHub account owns (``github_installations.account_id == user.github_id``).
  These stay under the SPA's ``Repositories`` page.
* **organization** — repositories of installations belonging to an org in
  which the caller holds a **live** ``org_members`` row AND either

  - the caller's ``org_members.role`` in that org is ``ORG_ADMIN`` — the
    explicit org-scoped role written by provisioning or a role edit —
    so administrators keep managing their organization's repositories,
    **or**
  - the repository carries an explicit ``org_member_repos`` grant row for
    the caller (written only by an *accepted* repo-scoped invitation).

  The global realm role deliberately does not widen repository
  visibility. Every login here is GitHub-brokered, and a broker signup
  without an explicit claim derives the global ``ORG_ADMIN`` *default*
  (``roles.py::derive_role``); letting that default floor repository
  reads would hand an invited REVIEWER the inviter's whole organization —
  the exact leak this module prevents (acceptance criterion: "connecting
  GitHub never automatically grants visibility to every repository
  belonging to an organization"). The default keeps its intended jobs
  elsewhere (the invitation's org role is what governs settings and
  review actions via ``org_access`` — the "org role wins" rule,
  decisions #12 — unchanged).

  The caller's own installations are never organization repositories — a
  solo user's repos appear once, under *Repositories*. A membership with
  no grants never falls back to the whole org: the grant subquery
  semi-joins ``org_members`` so a stale grant left behind by a removed
  member is dead.
* **all** (the union) — what the SPA's owner/name resolution and the
  dashboard count on: granted/admin organization repositories stay
  resolvable so deep links work, ungranted ones 404.

``PLATFORM_ADMIN`` keeps the documented F2 read bypass (reads everything;
the personal/organization split still applies mechanically). Guards raise
one uniform 404 — a caller must not learn whether an ungranted repository
exists. Mutations (PATCH/enable/disable/delete) are guarded separately by
``org_access.require_repository_access`` (org-membership role checks,
decisions #12).

Not used for authorization elsewhere: review/PR-detail routes stay
org-scoped by design (see docs/BACKEND_GAPS_FOR_UI.md §3).
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    OrgMemberRepo,
    Repository,
    User,
)
from app.security.roles import ROLE_ORG_ADMIN, ROLE_PLATFORM_ADMIN

logger = logging.getLogger(__name__)

#: values accepted by ``GET /repositories?visibility=``
VISIBILITY_VALUES = ("all", "personal", "organization")


def _not_found() -> HTTPException:
    """Uniform 404 — unknown and ungranted repositories are indistinguishable."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found"
    )


def personal_repositories_condition(user: User) -> ColumnElement[bool]:
    """Repositories of installations the caller's own GitHub account owns.

    ``false()`` when the caller has no GitHub identity — a Keycloak-only
    user owns nothing.
    """
    if user.github_id is None:
        return false()
    return GitHubInstallation.account_id == user.github_id


def _granted_repository_ids(user: User):
    """Subquery: repository ids explicitly granted to the caller.

    The semi-join on ``org_members`` (same org, same user) keeps a grant
    alive only while the membership itself exists — removing a member must
    not leave their old ``org_member_repos`` rows readable.
    """
    return (
        select(OrgMemberRepo.repo_id)
        .join(
            OrgMember,
            and_(
                OrgMember.org_id == OrgMemberRepo.org_id,
                OrgMember.user_id == OrgMemberRepo.user_id,
            ),
        )
        .where(OrgMemberRepo.user_id == user.id)
    )


def _admin_member_installation_ids(user: User):
    """Subquery: numeric installation ids of orgs the caller administers.

    Administration is judged by the **org-scoped** membership role only
    (``org_members.role == ORG_ADMIN``): that row is written by the
    provisioning seed or a role edit — the authoritative statement of who
    runs THIS org.

    The global realm role deliberately does NOT widen repository
    visibility (user-confirmed product rule, 2026-10-09): every login is
    GitHub-brokered here, and a broker signup without an explicit claim
    derives the global ``ORG_ADMIN`` *default* (roles.py derive_role). If
    that default floored repository reads, an invited REVIEWER would see
    the inviter's every repository — exactly the leak this module exists
    to prevent, and what the acceptance criteria forbid ("connecting
    GitHub never automatically grants visibility to every repository
    belonging to an organization"). The default still does what it was
    designed for (the invitation's org role governs settings and review
    actions via ``org_access`` — the "org role wins" rule, decisions
    #12 — not repository reads).
    ``PLATFORM_ADMIN`` callers never reach this function (read bypass).
    """
    return (
        select(GitHubInstallation.installation_id)
        .join(Org, Org.installation_id == GitHubInstallation.installation_id)
        .join(
            OrgMember,
            and_(OrgMember.org_id == Org.id, OrgMember.user_id == user.id),
        )
        .where(OrgMember.role == ROLE_ORG_ADMIN)
    )


def organization_repositories_condition(user: User) -> ColumnElement[bool]:
    """Organization repositories visible to the caller (never their own).

    Admin-member orgs contribute every repository; non-admin memberships
    contribute exactly the granted repositories. The caller's own
    installations are excluded — those are personal repositories.
    """
    visible: ColumnElement[bool] = or_(
        GitHubInstallation.installation_id.in_(_admin_member_installation_ids(user)),
        Repository.id.in_(_granted_repository_ids(user)),
    )
    if user.github_id is not None:
        visible = and_(visible, GitHubInstallation.account_id != user.github_id)
    return visible


def visible_repositories_condition(
    user: User, visibility: str = "all"
) -> ColumnElement[bool] | None:
    """WHERE fragment for a ``Repository``-select joined to its installation.

    ``None`` means "no restriction" — used only for the PLATFORM_ADMIN
    ``all`` bypass (reads everything, flag F2). Callers must be querying
    ``Repository`` joined to ``GitHubInstallation`` (FK default).
    """
    if visibility not in VISIBILITY_VALUES:
        raise ValueError(
            f"unknown visibility {visibility!r}; expected one of {VISIBILITY_VALUES}"
        )

    if user.role == ROLE_PLATFORM_ADMIN:
        # F2 read bypass: everything. The split still applies mechanically —
        # own-account installations are personal, the rest organization.
        if visibility == "personal":
            return personal_repositories_condition(user)
        if visibility == "organization":
            if user.github_id is None:
                return None
            return GitHubInstallation.account_id != user.github_id
        return None

    if visibility == "personal":
        return personal_repositories_condition(user)
    if visibility == "organization":
        return organization_repositories_condition(user)
    return or_(
        personal_repositories_condition(user),
        organization_repositories_condition(user),
    )


async def ensure_repository_visible(
    db: AsyncSession, user: User, repository: Repository
) -> None:
    """Guard a single repository read; uniform 404 when out of scope.

    ``repository.installation`` must be loaded (callers already
    ``selectinload`` it). Mirrors :func:`visible_repositories_condition`
    exactly so a repository resolvable through the list is fetchable by id
    and vice versa — the SPA resolves owner/name through the list, then
    fetches by UUID.
    """
    if user.role == ROLE_PLATFORM_ADMIN:
        return

    installation = repository.installation
    if installation is None:
        # Dangling installation FK — treat exactly like an invisible one.
        raise _not_found()

    if user.github_id is not None and installation.account_id == user.github_id:
        return  # own account's installation → personal repository

    membership_role = (
        await db.execute(
            select(OrgMember.role)
            .join(Org, Org.id == OrgMember.org_id)
            .where(
                Org.installation_id == installation.installation_id,
                OrgMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if membership_role == ROLE_ORG_ADMIN:
        # Administrator of this repository's org — the explicit org-scoped
        # membership role. The global realm role (including the GitHub-signup
        # ORG_ADMIN default) deliberately does not reach here: it must not
        # override the inviter's repository selection. See
        # _admin_member_installation_ids for the full rationale.
        return

    # Every other membership (REVIEWER/DEVELOPER) and no-membership-at-all
    # both land here: only an explicit org_member_repos grant can make the
    # repository readable. The grant subquery semi-joins org_members, so a
    # grant whose membership row is gone is already dead.

    grant = (
        await db.execute(
            select(OrgMemberRepo.id)
            .join(
                OrgMember,
                and_(
                    OrgMember.org_id == OrgMemberRepo.org_id,
                    OrgMember.user_id == OrgMemberRepo.user_id,
                ),
            )
            .where(
                OrgMemberRepo.user_id == user.id,
                OrgMemberRepo.repo_id == repository.id,
            )
            .limit(1)
        )
    ).first()
    if grant is not None:
        return

    raise _not_found()


async def org_attribution(
    db: AsyncSession, repositories: Sequence[Repository]
) -> dict[UUID, tuple[UUID, str]]:
    """``repositories.id`` → ``(org_id, org_name)`` for the given rows.

    Viewer-independent attribution — the org of the repository's
    installation, whether or not the viewer calls it an organization
    repository (a personal installation also has a provisioned org row;
    the *personal vs organization* split lives in the visibility
    conditions, not here). Repositories without an org row are absent
    from the map (callers render null attribution).
    """
    if not repositories:
        return {}
    rows = (
        await db.execute(
            select(Repository.id, Org.id, Org.name)
            .join(
                GitHubInstallation, GitHubInstallation.id == Repository.installation_id
            )
            .join(Org, Org.installation_id == GitHubInstallation.installation_id)
            .where(Repository.id.in_([repo.id for repo in repositories]))
        )
    ).all()
    return {repo_id: (org_id, org_name) for repo_id, org_id, org_name in rows}
