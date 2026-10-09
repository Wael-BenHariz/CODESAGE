# RBAC Endpoint Inventory (workspace RBAC)

Every API endpoint in `backend/app/api/routes/` and the authorization it enforces.
The single source of truth for the permission lists and the ladder is
`backend/app/security/workspace_access.py` (`PERMISSION_MAP`, `RANK`);
row-level org access lives in `backend/app/security/org_access.py`.
The capability matrix is `docs/rbac-target-design.md` §2.3; business rules are §2.5.

## How a guarded request is evaluated

1. **Resolve the workspace** — explicit `workspace_id` (path/query), else the
   endpoint's resource (repository → pull request → review → review comment →
   GitHub installation → its `workspace_id`), else the optional `X-Workspace-Id`
   header.
2. **No workspace context** → fall back to the *global* JWT role against the
   permission's lowest allowed role (pre-workspace behaviour — unbound/legacy
   data is never stricter and never looser than before).
3. **Workspace context** → the caller must hold a membership row
   (`workspace_members`, or `org_members` of the org linked to that workspace —
   both are read and written together). Non-member → uniform **404**
   (existence must not leak); unknown workspace id → **404**;
   `PLATFORM_ADMIN` passes the membership step.
4. **Effective role** = `max(JWT realm role, membership role)` on the ladder
   `PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE`; below the
   permission's threshold → **403** (`"Insufficient permissions"` — never
   echoes which roles exist).

## Permission lists (§2.3)

| Permission | Lowest role | Roles |
|---|---|---|
| `view` | NONE | NONE, DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN |
| `trigger` | DEVELOPER | DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN |
| `request` | DEVELOPER | DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN |
| `review` | REVIEWER | REVIEWER, ORG_ADMIN, PLATFORM_ADMIN |
| `repo_config` | REVIEWER | REVIEWER, ORG_ADMIN, PLATFORM_ADMIN |
| `repo_admin` | ORG_ADMIN | ORG_ADMIN, PLATFORM_ADMIN |
| `platform` | PLATFORM_ADMIN | PLATFORM_ADMIN |

`capability_flags(role)` derives the frontend's `capabilities` payload for
`GET /auth/me` — the UI renders from those flags and never re-derives role lists.

---

## Endpoint inventory

Legend for **Guard**:
- *workspace: X* — `require_workspace_permission("X")` / `check_permission_in_workspace(..., "X")`
- *org: read/write* — `org_access.require_*` (row reached through
  review → PR → repo → installation → org; `write=True` rejects NONE first;
  reads allow PLATFORM_ADMIN without membership, listed carve-outs below do not)
- *global* — realm-role dependency only (`require_developer` = effective DEVELOPER,
  `require_super_admin` = PLATFORM_ADMIN, `require_role(...)`)
- *auth* — any authenticated user (data visibility is scoped by query)

### Workspaces — `/api/v1/workspaces`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /workspaces` | auth | Returns the caller's workspaces with effective roles; idempotently ensures the PERSONAL workspace exists |
| `POST /workspaces?name=` | global ∈ {ORG_ADMIN, PLATFORM_ADMIN} | Creates an ORG workspace (no `platform` requirement — an org admin can create their own) |
| `GET /workspaces/{id}` | workspace:`view` | |
| `PATCH /workspaces/{id}` | workspace:`repo_admin` | |
| `DELETE /workspaces/{id}` | workspace:`repo_admin` | |
| `GET /workspaces/{id}/members` | workspace:`view` | |
| `PATCH /workspaces/{id}/members/{user_id}?role=` | workspace:`repo_admin` | Last-ORG_ADMIN guard; role written to `workspace_members` **and** `org_members` (`NONE` ⇒ org row removed) |
| `DELETE /workspaces/{id}/members/{user_id}` | workspace:`repo_admin` | Last-ORG_ADMIN guard; deletes from both tables |

### Repositories — `/api/v1/repositories`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /repositories` | auth | Visibility: installer + members of the org seeded from the installation |
| `GET /repositories/{id}`, `GET /repositories/{id}/detail` | auth | Same visibility rule |
| `POST /repositories/connect` | workspace:`repo_config` | |
| `PATCH /repositories/{id}` | workspace:`repo_config` | Default branch, auto-review toggle, … |
| `POST /repositories/{id}/enable` / `/disable` | workspace:`repo_config` | Mirrors to `repo-tenant-service` best-effort |
| `DELETE /repositories/{id}` | workspace:`repo_admin` | |
| `POST /repositories/installations/sync` | workspace:`repo_admin` | |
| `GET /repositories/install-url` | auth | Legacy unbound install URL |
| `GET /repositories/github` | auth | Available GitHub repos for the installation |

### GitHub App install — `/api/v1/auth`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /auth/github/app/install-url?workspace_id=` | workspace:`repo_admin` (when `workspace_id` given) | Omitting it keeps the legacy unbound flow; the chosen workspace id is signed into the state token (`wid`) and written back on the callback |

### Pull requests — `/api/v1/pulls`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /pulls/repository/{repository_id}` | org: read (`view`) | |
| `GET /pulls/{pull_request_id}` | org: read (`view`) | |
| `GET /pulls/{pull_request_id}/reviews` | org: read (`view`) | |
| `POST /pulls/{pull_request_id}/review` | global `require_developer` + org: write ≥ DEVELOPER (`trigger`) | |

### Reviews — `/api/v1/reviews`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /reviews` | auth | Visibility-scoped list |
| `GET /reviews/{id}` | org: read (`view`) | Exposes `viewer_role` for UI gating |
| `GET /reviews/{id}/scan-report` | org: read (`view`) | 404 passes through as "no enrichment" in the UI |
| `GET /reviews/{id}/status` | org: read (`view`) | |
| `POST /reviews/{id}/retry` | global `require_developer` + org: write ≥ DEVELOPER (`trigger`) | |
| `DELETE /reviews/{id}` | global `require_developer` + org: write ≥ DEVELOPER (`trigger`) | |
| `PATCH /reviews/{id}/comments/{cid}/resolve` | global `require_developer` + org: write ≥ DEVELOPER (`trigger`) | |
| `PATCH /reviews/{id}/summary` | org: write ≥ REVIEWER (`review`), **no PLATFORM_ADMIN bypass** | State check (§2.5) |
| `PATCH /reviews/{id}/comments/{cid}/dismiss` | org: write ≥ REVIEWER (`review`), no platform bypass | State check + **self-review rule** |
| `PATCH /reviews/{id}/comments/{cid}/restore` | org: write ≥ REVIEWER (`review`), no platform bypass | State check; self-review deliberately *not* applied (un-hiding a finding never benefits the author) |
| `PATCH /reviews/{id}/comments/{cid}/validate` | org: write ≥ REVIEWER (`review`), no platform bypass | State check + **self-review rule** |
| `POST /reviews/{id}/post` | org: write ≥ REVIEWER (`review`), no platform bypass | Under `FOR UPDATE`: staged + not posted + ready (each 409) + **pending dismissal requests block posting** (409) |

The "no PLATFORM_ADMIN bypass" carve-out (F2) means a platform admin must be an
actual org member to edit/dismiss/validate/post on a customer's PR.

### Dismissal requests — `/api/v1/dismissal-requests`

| Method + path | Permission | Notes |
|---|---|---|
| `POST /dismissal-requests?review_comment_id=&reason=` | workspace:`request` | DEVELOPER+ may *ask*; status starts `PENDING` |
| `GET /dismissal-requests?workspace_id=&status_filter=` | auth | Only workspaces the caller is a member of |
| `PATCH /dismissal-requests/{id}/approve` | workspace:`review` | State check: blocked once the review is posted; approving dismisses the finding |
| `PATCH /dismissal-requests/{id}/reject` | workspace:`review` | Same state check |

### Install requests — `/api/v1/install-requests`

| Method + path | Permission | Notes |
|---|---|---|
| `POST /install-requests?workspace_id=` | workspace:`trigger` | The §2.5 "Request GitHub App install" flow; notifies ORG_ADMINs in-app |
| `GET /install-requests?workspace_id=&status_filter=` | auth | Only accessible workspaces |
| `PATCH /install-requests/{id}/approve` / `/reject` | workspace:`repo_admin` | ORG_ADMIN+ resolves |

### Notifications — `/api/v1/notifications`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /notifications?workspace_id=` | workspace:`view` when `workspace_id` given; otherwise the caller's own rows | |
| `PATCH /notifications/{id}/read` | own row | |
| `PATCH /notifications/read-all` | workspace:`view` when `workspace_id` given; otherwise own rows | |
| `DELETE /notifications/{id}` | own row | |

### Orgs & invitations (org-scoped, synced with workspaces)

These still use `org_access.require_org_role`; on invitation acceptance and role
changes the membership is mirrored into `workspace_members` (020 backfill +
`sync_membership_role`), so the two models never disagree.

| Method + path | Permission |
|---|---|
| `GET /orgs` | auth (caller's orgs) |
| `GET /orgs/{id}/settings` | org read (ORG_ADMIN+) |
| `PUT /orgs/{id}/settings` | org write (ORG_ADMIN, no platform bypass on write) |
| `POST /orgs/{id}/invitations` (incl. `repository_ids`) | ORG_ADMIN write, **no platform bypass** |
| `GET /orgs/{id}/invitations` | ORG_ADMIN read |
| `GET /invitations/{token}` / `POST /invitations/{token}/accept` | token-based (preview + accept) |

### Platform, users, settings, misc

| Method + path | Permission | Notes |
|---|---|---|
| `GET/PUT /platform/settings` | platform (`require_super_admin`) | |
| `GET /users`, `GET /users/{id}` | platform (`require_super_admin`) | |
| `GET /users/me`, `PATCH /users/me`, `DELETE /users/me` | self | |
| `GET /settings/llm` | self | Per-user LLM settings |
| `PUT/DELETE /settings/llm`, `POST /settings/llm/test` | global `require_developer` | Per-user data; gated so anonymous/NONE sessions cannot poke it |
| `GET /github/status`, `GET /github/repos` | auth | Legacy repo-selection views |
| `POST /github/repos/selection` | global `require_developer` | |
| `POST /webhooks/github` | HMAC signature (`GITHUB_WEBHOOK_SECRET`) | |
| `GET /health`, `/health/ready`, `/health/live` | public | |
| `GET /auth/keycloak/config` | public | |
| `GET /auth/me` | auth | Emits `capabilities` per workspace from `capability_flags()` |
| `POST /auth/logout` | auth | |
| `GET /auth/github/app/callback` | signed state token | |

---

## Server-side business rules (§2.5)

| Rule | Enforced in | Behaviour |
|---|---|---|
| Actionable state | `reviews._ensure_actionable` | `status == 'ready_to_post'` AND `posted_at IS NULL`, else 409 — applies to summary edit, dismiss, restore, validate; `POST /post` re-checks under a row lock |
| Pending dismissal requests block posting | `reviews.post_review_now` | Any `DismissalRequest.status == 'PENDING'` on the review → 409 (checked under `FOR UPDATE`) |
| Self-review rule | `workspace_access.self_review_blocked` → `reviews` (dismiss, validate), `dismissal_requests.approve` | Active only in an ORG workspace with >1 member; case-insensitive PR-author login compare; disabled for PERSONAL/single-member workspaces |
| Last-ORG_ADMIN guard | `workspaces.py` | Cannot demote/remove the final ORG_ADMIN of an ORG workspace |
| F1 removed | `roles.py` | GitHub-broker logins get global `NONE`; roles come only from workspace membership (personal workspace owner is ORG_ADMIN by construction) |

## Frontend mirror (cosmetic only)

Routes declare `data: { capabilities: [...] }`; `role.guard.ts` resolves the
effective role (server `auth/me` workspace role, else JWT `deriveRole`) and asks
`canCapability()` — a permission name, never a role list. `AuthContextService.can()`
shapes nav/controls cosmetically; **the backend re-authorizes every request**, so
UI gating failures are a UX issue, never a security one.
