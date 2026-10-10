# RBAC Endpoint Inventory (simple RBAC — orgs + invitations only)

Every API endpoint in `backend/app/api/routes/` and the authorization it enforces.
The workspace layer (v0.5.0) was **removed** in v0.6.0 (decisions #12, migration 023).
The single source of truth for the permission lists and the ladder is
`backend/app/security/roles.py` (`PERMISSION_MAP`, `RANK`, `capability_flags`);
row-level org access lives in `backend/app/security/org_access.py`.
The capability matrix is `docs/rbac-target-design.md` §2.3; business rules are §2.5.

## How a guarded request is evaluated

1. **NONE sentinel** — a write with JWT role `NONE` → **403** before any lookup
   (the JWT decides this sentinel, nothing else).
2. **Resolve the org** — through the endpoint's resource chain
   (repository → installation → org; review → pull request → repo →
   installation → org). Unknown id and cross-org raise the *same* uniform
   **404** (existence must not leak).
3. **Membership** — the caller needs an `org_members` row. No row → uniform
   **404**, except reads where `PLATFORM_ADMIN` passes without membership (F2);
   the listed F2 carve-outs (summary edit / dismiss / restore / validate / post)
   pass `platform_admin_bypass=False`, so a platform admin must be a real org
   member to touch a customer's PR.
4. **Effective role = `org_members.role`** (the org role wins — invitations,
   provisioning seeds and installs decide it; the JWT never elevates or lowers
   a member, decisions #12). Below the permission's threshold → **403**
   (`"Insufficient permissions"` — never echoes which roles exist).

Ladder: `PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE`.

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

(`request` is kept in the map for the capability payload's shape; the
dismissal/install *request* features it fed were removed with the workspace
layer.)

`capability_flags(role)` derives the frontend's `capabilities` payload for
`GET /auth/me` — the UI renders from those flags and never re-derives role lists.

---

## Endpoint inventory

Legend for **Guard**:
- *repo: X* — `require_repository_access("X")` (repository → installation → org;
  `write=True` rejects NONE first)
- *org: read/write* — `org_access.require_*` (row reached through
  review → PR → repo → installation → org; `write=True` rejects NONE first;
  reads allow PLATFORM_ADMIN without membership, listed carve-outs below do not)
- *global* — realm-role dependency only (`require_developer` = effective DEVELOPER,
  `require_super_admin` = PLATFORM_ADMIN, `require_role(...)`)
- *auth* — any authenticated user (data visibility is scoped by query)

### Repositories — `/api/v1/repositories`

Read visibility (`app/services/repository_visibility.py`, repo-scoped invitations):

- **personal** — installations owned by the caller's GitHub account (`account_id == github_id`);
- **organization** — installations of orgs with a **live** membership where the caller's
  org-scoped role is `ORG_ADMIN` (`org_members.role` — written by provisioning or
  invitation acceptance) **or** the repository carries an explicit
  `org_member_repos` grant (accepted invitations only; a stale grant without a membership
  row is dead). The **global realm role does not widen repository visibility** — every
  GitHub-broker signup derives the global `ORG_ADMIN` default, and treating it as a floor
  would hand an invited REVIEWER the inviter's whole org (user-confirmed rule, 2026-10-09);
- PLATFORM_ADMIN keeps the F2 read bypass. Responses carry the installation's org
  attribution (`org_id`/`org_name`, viewer-independent).

| Method + path | Permission | Notes |
|---|---|---|
| `GET /repositories` | auth | Visibility above; `?visibility=all\|personal\|organization` selects the collection (default `all` = the union the SPA's owner/name resolution and the dashboard use) |
| `GET /repositories/{id}`, `GET /repositories/{id}/detail` | auth | Same visibility rule — uniform 404 outside it (previously any authenticated caller could read any repository by UUID) |
| `POST /repositories/connect` | global `require_developer` | |
| `PATCH /repositories/{id}` | repo: REVIEWER (`repo_config`) | Default branch, auto-review toggle, … |
| `POST /repositories/{id}/enable` / `/disable` | repo: REVIEWER (`repo_config`) | Mirrors to `repo-tenant-service` best-effort |
| `DELETE /repositories/{id}` | repo: ORG_ADMIN (`repo_admin`) | |
| `POST /repositories/installations/sync` | global `require_developer` | |
| `GET /repositories/install-url` | auth | Legacy unbound install URL |
| `GET /repositories/github` | auth | Available GitHub repos for the installation |

### GitHub App install — `/api/v1/auth`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /auth/github/app/install-url` | auth | Signed state carries the user id only; the callback runs org provisioning — the installation **auto-creates its org** with the installer seeded as `ORG_ADMIN` (least privilege, decisions #12 rule 3) |

### Pull requests — `/api/v1/pulls`

| Method + path | Permission | Notes |
|---|---|---|
| `GET /pulls/repository/{repository_id}` | auth + repository visibility | Same read scope as `GET /repositories` (uniform 404 outside it) |
| `GET /pulls/{pull_request_id}` | org: read (`view`) | |
| `GET /pulls/{pull_request_id}/reviews` | org: read (`view`) | |
| `POST /pulls/{pull_request_id}/review` | org: write ≥ DEVELOPER (`trigger`) | NONE sentinel first (403); cross-org/unknown → 404 |

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
| `PATCH /reviews/{id}/comments/{cid}/dismiss` | org: write ≥ REVIEWER (`review`), no platform bypass | State check |
| `PATCH /reviews/{id}/comments/{cid}/restore` | org: write ≥ REVIEWER (`review`), no platform bypass | State check |
| `PATCH /reviews/{id}/comments/{cid}/validate` | org: write ≥ REVIEWER (`review`), no platform bypass | State check |
| `POST /reviews/{id}/post` | org: write ≥ REVIEWER (`review`), no platform bypass | Under `FOR UPDATE`: staged + not posted + ready (each 409) |

The "no PLATFORM_ADMIN bypass" carve-out (F2) means a platform admin must be an
actual org member to edit/dismiss/validate/post on a customer's PR.

### Orgs & invitations (org-scoped)

These use `org_access.require_org_role`; the invitation's role is written to
`org_members` on acceptance (decisions #12 — the org role is the only in-org
ladder input).

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
| `GET /auth/me` | auth | Emits the global role + `capabilities` from `capability_flags()` |
| `POST /auth/logout` | auth | |
| `GET /auth/github/app/callback` | signed state token | Provisions installation + auto-org (rule 3) |

---

## Server-side business rules (§2.5)

| Rule | Enforced in | Behaviour |
|---|---|---|
| Actionable state | `reviews._ensure_actionable` | `status == 'ready_to_post'` AND `posted_at IS NULL`, else 409 — applies to summary edit, dismiss, restore, validate; `POST /post` re-checks under a row lock |
| Org role wins | `org_access._effective_role` | Effective role inside an org is `org_members.role` — the JWT decides only the NONE write sentinel and the no-membership PLATFORM_ADMIN bypass (no `max()`) |
| Install auto-org | `auth.github_app_callback` → `org_provisioning` | GitHub App install creates the org (idempotent) and seeds the installer as ORG_ADMIN; least-privilege seeding keeps any linked collaborator's row at their existing role |
| Invitation role | `invitations.accept` | Accept writes the invitation's role to `org_members` (repo-scoped grants also write `org_member_repos` + `watched_repos`) |
| F1 removed | `roles.py` | GitHub-broker logins with no recognized claim get global `ORG_ADMIN` (signup default, owner decision 2026-10-09); any explicit claim outranks it and non-brokered tokens stay `NONE` |

## Frontend mirror (cosmetic only)

Routes declare `data: { capabilities: [...] }`; `role.guard.ts` resolves the
effective role (server `auth/me` role, else JWT `deriveRole`) and asks
`canCapability()` — a permission name, never a role list. `AuthContextService.can()`
shapes nav/controls cosmetically; **the backend re-authorizes every request**, so
UI gating failures are a UX issue, never a security one.
