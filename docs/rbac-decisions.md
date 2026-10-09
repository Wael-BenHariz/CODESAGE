# RBAC Decisions Log

This document tracks assumptions and decisions made during the RBAC implementation process.

**Status (v0.5.0, branch `feat/workspace-rbac`)**: all initial assumptions were
confirmed by discovery and all open questions below are now **resolved** — see
"Resolved Decisions". The endpoint-level outcome of these decisions is
documented in `docs/rbac-endpoints.md`; the enforced matrix in
`docs/rbac-target-design.md` §2.3–§2.5.

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
    first login already creates their personal workspace with an ORG_ADMIN
    membership row, and the global default makes `users.role`, `/auth/me` and
    cold-start route gating agree with that from the first request.
    Constraints kept: any explicit claim still outranks the default (a
    `GUEST` downgrade stays `NONE`, `PLATFORM_ADMIN` still wins), non-brokered
    tokens without a recognized claim stay fail-closed `NONE`, and platform
    routes remain `platform: false` (PLATFORM_ADMIN only). Known trade-off:
    effective role = `max(JWT, membership)`, so a brokered user holds an
    ORG_ADMIN floor inside **every** org they are a member of — inviting one
    as `DEVELOPER` does not lower them while their token carries no explicit
    role.