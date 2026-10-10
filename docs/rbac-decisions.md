# RBAC Decisions Log

This document tracks assumptions and decisions made during the RBAC implementation process.

**Status (v0.6.0 "Simple RBAC", branch `feat/workspace-rbac`)**: all initial
assumptions were confirmed by discovery and all open questions below are now
**resolved** — see "Resolved Decisions"; **#12 removes the workspace layer
itself** and supersedes the workspace-based decisions above it. The
endpoint-level outcome is documented in `docs/rbac-endpoints.md`; the enforced
matrix in `docs/rbac-target-design.md` §2.3–§2.5.

## Initial Assumptions (from discovery phase)

1. **Role Precedence Bug Confirmed**: The current implementation in `/backend/app/security/roles.py` lines 78-82 shows precedence as `PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER`, which incorrectly places NONE above ORG_ADMIN. This needs to be fixed to `PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE`.

2. **F1 Temporary Role Exists**: The temporary F1 DEVELOPER role for GitHub-brokered logins is present in the code (roles.py lines 84-90 and 107-116) and needs to be removed per the requirements.

3. **Workspace Concept Missing**: There is no explicit workspace model in the current schema. Organizations implicitly define scope through the orgs table and org_memberships.

4. **Authorization Scattered**: Permission checks are distributed across various files:
   - Role-based guards in `/backend/app/security/roles.py`
   - Org-scoped guards in `/backend/app/security/org_access.py`
   - Direct role checks in API route files

5. **Frontend-Backend Duplication**: Role constants and logic are duplicated between backend and frontend:
   - Backend: `/backend/app/security/roles.py`
   - Frontend: `/frontend/src/app/core/guards/role.guard.ts` and related services

6. **Field Naming Inconsistency**: The task mentions renaming to `viewer_role` consistently and removing `reviewer_role`. Need to investigate where these fields exist.

## Resolved Decisions (answers to the former Open Questions)

1. **Workspace Type Values** → Plain strings `"PERSONAL"` / `"ORG"`, enforced by a
   DB check constraint (`ck_workspaces_type` in migration 020). No enum table —
   the vocabulary is tiny and mirrors the existing role-string convention.

2. **Personal Workspace Naming** → `"{login}'s workspace"` (e.g.
   `octocat's workspace`), created in `workspace_access.ensure_personal_workspace`.
   Display-only; the unique key is `(type, owner_user_id)`.

3. **Migration Strategy** → Alembic `020` performs all four steps in one
   transaction: one PERSONAL workspace per existing user; one ORG workspace per
   existing org (with `github_account_login`); `org_members` → `workspace_members`
   seeded from `orgs.workspace_id`; repositories, pull requests, reviews,
   watched repos and GitHub installations bound to a workspace through the
   installation → org → workspace chain (linker's personal workspace as
   fallback, org ownership wins when both apply). Columns are nullable —
   unbound rows fall back to the global JWT role, so nothing gets stricter
   mid-migration.

4. **GitHub App Installation Ownership** → Installations belong to a workspace:
   `github_installations.workspace_id` (migration 020), bound from the signed
   install state (`wid`) on the App callback and from the webhook provisioning
   chain. The install URL endpoint enforces `repo_admin` in the target workspace.

5. **Personal Workspace Creation Timing** → Idempotent, on first login
   (`ensure_personal_workspace` — select-then-create, also ensures the explicit
   ORG_ADMIN membership row). Pre-seeded for existing users by the 020 backfill;
   no background process needed.

6. **Default Workspace Context** → No server-side "current workspace": every
   request carries its own context (`workspace_id` param, resource traversal, or
   `X-Workspace-Id` header). The frontend remembers a stored selection
   (`codesage_active_workspace`) and defaults to the personal workspace, else the
   first workspace (`auth-context.service.ts`).

7. **Cross-Workspace Access** → Uniform **404** (`"Resource not found"`) for
   unknown workspace ids and non-members alike — existence must not leak; 403 is
   reserved for "you are a member but under-qualified" (`"Insufficient
   permissions"`, no role names echoed).

8. **Platform Admin Scope** → Truly global; never a membership row. It bypasses
   the *membership* step on workspace endpoints, but the F2 carve-out still
   applies: summary edit / dismiss / restore / validate / post go through
   `org_access` with `platform_admin_bypass=False`, so a platform admin must be
   a real org member to touch a customer's PR. An explicit `NONE` downgrade is
   never outranked (NONE sits at rank 0 on the ladder).

9. **Role Field Migration** → The response field is `viewer_role` (review
   detail payload); `reviewer_role` no longer exists anywhere in backend or
   frontend (verified by grep). Internal comparisons use the explicit
   permission lists in `workspace_access.PERMISSION_MAP`, never `!== 'NONE'`.

10. **Backwards Compatibility** → Additive only: existing endpoints keep their
    paths and shapes; new payloads (`capabilities`, `viewer_role`, workspace
    objects) are additions. Legacy role tokens were mapped for one release
    (`SUPER_ADMIN→PLATFORM_ADMIN`, `GUEST→NONE`) and removed in v0.4.0. Data
    without a `workspace_id` is evaluated exactly as before (global role), so
    un-migrated rows behave identically for old clients. The old frontend
    `deriveRole` is retained purely as the JWT fallback for tokens issued before
    `/auth/me` carried capabilities.

11. **Brokered Signup Default** (2026-10-09, owner decision — supersedes the
    "broker logins get global `NONE`" wording above/below) → a GitHub-brokered
    token with **no recognized role claim** derives global **`ORG_ADMIN`**
    (`derive_role(via_github=True)`; mirrored by the frontend `deriveRole`).
    Rationale: a GitHub signup should land as an org-admin from day one —
    the global default makes `users.role`, `/auth/me` and cold-start route
    gating agree with that from the first request; in-org power is then
    decided by membership (install seeds ORG_ADMIN, invitation sets the
    invited role — #12).
    Constraints kept: any explicit claim still outranks the default (a
    `GUEST` downgrade stays `NONE`, `PLATFORM_ADMIN` still wins), non-brokered
    tokens without a recognized claim stay fail-closed `NONE`, and platform
    routes remain `platform: false` (PLATFORM_ADMIN only). ~~Known trade-off:
    effective role = `max(JWT, membership)`~~ — **superseded by #12**: the
    effective role inside an org is the membership role alone, so inviting a
    brokered ORG_ADMIN as `DEVELOPER` does lower them in that org.

12. **Simple RBAC: the workspace layer is removed** (2026-10-10, owner
    decision — supersedes the workspace-based decisions 4, 5, 6 (and #9's
    `workspace_access.PERMISSION_MAP` pointer); Alembic **023**, version
    `v0.6.0`) →

    **Model.** Orgs + `org_members` only: no `workspaces`/`workspace_members`,
    no workspace switcher or per-workspace roles, and all governance features
    that hung off them are dropped without replacement — dismissal requests,
    install requests, in-app notifications, and the self-review rule.
    `workspace_id` columns/indexes are gone from `repositories`,
    `github_installations`, `reviews`, `pull_requests`, `watched_repos` and
    `orgs` (023's `downgrade()` recreates the 020–022 structure, minus
    backfill, for one release of rollback room).

    **Account creation = ORG_ADMIN.** A GitHub-brokered signup derives the
    global `ORG_ADMIN` default (#11). Installing the GitHub App auto-creates
    the org for that installation (idempotent upsert, shared by the callback
    and the webhook) and seeds the installer as `ORG_ADMIN` via the existing
    least-privilege rule (exactly one linked user → ORG_ADMIN; ≥2 → all
    DEVELOPER; 0 → none; existing rows never changed). An invitation link
    grants exactly the invitation's role on acceptance — nothing more.

    **Org role wins inside orgs.** Effective role = `org_members.role`, with
    **no `max(JWT, membership)`** — a member invited as DEVELOPER stays
    DEVELOPER in that org even though every GitHub session carries the global
    ORG_ADMIN default. The JWT decides only (a) the `NONE` write sentinel
    (403 before any lookup) and (b) the no-membership `PLATFORM_ADMIN` read
    bypass (F2; the F2 carve-outs still demand real membership). Non-members
    and unbound resources keep the uniform 404; below-threshold members keep
    the uniform 403.

    **Authorization surface.** `roles.py` hosts `RANK`/`PERMISSION_MAP`/
    `min_role_for`/`allowed`/`capability_flags` (moved out of the deleted
    `workspace_access.py`); `org_access.py` adds
    `require_repository_access(min_role, write=…)` (repository →
    installation → org, same 404 semantics) and `_effective_role` implements
    the membership-wins rule. `/auth/me` emits the global role plus
    `capabilities` from `capability_flags()` — no per-workspace payload.
    Repo mutations: `PATCH`/`enable`/`disable` = repository access ≥
    REVIEWER, `DELETE` = ORG_ADMIN; `connect`/`sync` are global
    `require_developer`. Unchanged: `viewer_role`, staged posting, invitation
    repo grants, repository visibility rules, frontend `deriveRole` fallback.