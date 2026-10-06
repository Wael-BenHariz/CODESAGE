# Frontend Screens & Routes (v0.3.2)

Inventory maintained for the UI-redesign release on `feat/ui-redesign`
(supersedes the `feat/frontend-api-coverage` inventory; the API-coverage
findings below are unchanged).
Endpoint-by-endpoint coverage: `docs/FRONTEND_GAP_MATRIX.md`.
Endpoints the UI needs but the backend does not expose:
`docs/BACKEND_GAPS_FOR_UI.md`.
Redesign plan, gates and screenshots: `docs/UI_REDESIGN_PLAN.md`,
`docs/ui/before/` (15) + `docs/ui/after/` (18).

---

## Routes → screen → guard

Role lists live in `frontend/src/app/core/guards/role.guard.ts`; the guard is
`RoleGuard` (keycloak-angular auth + role check, mirroring
`backend/app/security/roles.py`).

| Route                                    | Screen (component)                         | `data.roles`  | Notes                                                                    |
| ---------------------------------------- | ------------------------------------------ | ------------- | ------------------------------------------------------------------------ |
| `/`                                      | `landing`                                  | public        | Entry point.                                                             |
| `/login`                                 | `auth/login`                               | public        | Keycloak authorize (PKCE, `idpHint: github`).                            |
| `/github/callback`                       | `auth/github-callback`                     | **no guard**  | GitHub App post-install redirect; must render while the session restores. |
| `/invite/accept`                         | `invitations/invite-accept`                | **no guard**  | Invitee has no session yet: public preview, explicit Accept.             |
| `/help`                                  | `help`                                     | **no guard**  | Public explainer (redesign Step 9): `data: { shell: false }`, shared copy. |
| `/dashboard`                             | `dashboard`                                | `WRITE_ROLES` | Real API stats (Step 10): repo counts + review totals + recent reviews.  |
| `/repositories`                          | `repositories/repository-list`             | `ANY_ROLE`    | Install / connect / enable / disable / remove + selection modal.         |
| `/repositories/:owner/:repo`             | `repositories/repository-detail`           | `ANY_ROLE`    | `owner/name` → repo UUID resolver (Step 2).                              |
| `/repositories/:owner/:repo/pulls`       | `pull-requests/pr-list`                    | `ANY_ROLE`    | Paginated PRs of one repo (Step 2 mapping).                              |
| `/repositories/:owner/:repo/pulls/:number` | `pull-requests/pr-detail`                | `ANY_ROLE`    | PR detail + stats bar + review panel; `confirmUnsavedSummaryGuard` (Step 4). |
| `/settings`                              | `settings`                                 | `WRITE_ROLES` | LLM settings (write-only key) + disabled not-available sections (Step 8). |
| `/settings/org`                          | `settings/org-settings`                    | `ADMIN_ROLES` | Org settings + ceilings + embedded invitations (Steps 6/7).              |
| `/platform`                              | `admin/platform-admin`                     | `PLATFORM_ROLES` | Users + orgs, read-only (Step 9).                                      |
| `/not-found`, `**`                       | `errors/not-found`                         | —             | Generic 404 (rule: never "you don't have access" wording).               |
| `/forbidden`                             | `errors/forbidden`                         | —             | Role-guard denial target (unguarded, no redirect loop).                  |

Guard role lists:

| Constant        | Roles                                             | Semantics                                                                          |
| --------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `ANY_ROLE`      | DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN, NONE | Any authenticated user — mirrors the backend's "reads: any role".                |
| `WRITE_ROLES`   | DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN    | Mirrors `require_developer` (mutations).                                            |
| `ADMIN_ROLES`   | ORG_ADMIN, PLATFORM_ADMIN                         | Guard elevates via a `org_members` ORG_ADMIN row (`max(JWT, org-membership)`).      |
| `PLATFORM_ROLES`| PLATFORM_ADMIN                                    | Deliberately **not** in `ADMIN_ROLES` — no membership elevation can open it.        |

---

## Screens

Every data section implements the four states — **loading / empty /
error + retry / success** — and mutations disable their button while pending
(no double submit) with a visible success or error (toast or inline).

| Screen                | Backend route groups used                                        | Tests (spec)                                    |
| --------------------- | ---------------------------------------------------------------- | ----------------------------------------------- |
| landing               | — (public)                                                       | —                                               |
| auth/login            | `GET /auth/keycloak/config` (bootstrap)                          | —                                               |
| auth/github-callback  | `GET /github/status`, `POST /github/repos/selection`             | `github-callback.component.spec`                |
| help (public)         | — (static copy; no endpoint — never faked data)                  | `help.component.spec` (8)                       |
| dashboard             | `GET /repositories`, `GET /reviews` (+ `status_filter=pending`)  | `dashboard.component.spec` (7)                  |
| repository-list       | `GET /repositories`, `POST …/enable|disable`, `DELETE`, `GET /github/repos`, `POST /github/repos/selection`, install URL | `repository-list.component.spec` (12) |
| repository-detail     | `GET /repositories/{id}` (owner/name resolver), PR list          | `repository-detail.component.spec`              |
| pr-list               | `GET /pull-requests/repository/{id}`                             | `pr-list.component.spec`                        |
| pr-detail + review panel | `GET /pull-requests/{id}`, `GET /reviews/{id}`, `GET …/scan-report`, staged `PATCH/POST` verdicts (Steps 4/5) | `pr-detail.component.spec`, `review-panel.component.spec`, `pr-detail.guard.spec` |
| settings              | `GET|PUT|DELETE /settings/llm`, `POST /settings/llm/test`, `GET /auth/me` | `settings.component.spec`                 |
| org-settings          | `GET|PUT /orgs/{id}/settings`, `GET|PUT /platform/settings`      | `org-settings.component.spec`                   |
| org-invitations (embedded) | `GET|POST|DELETE /orgs/{id}/invitations`                    | `org-invitations.component.spec`                |
| platform-admin        | `GET /users`, `GET /orgs` (all orgs for PA)                      | `platform-admin.component.spec` (8)             |
| invite-accept         | `GET /invitations/{token}`, `POST /invitations/{token}/accept`   | `invite-accept.component.spec`                  |
| errors 403/404        | — (routed by interceptors/guard)                                 | `error-pages.spec`                              |
| site header (shared)  | `GET /orgs` (switcher), `can(action)` capabilities               | `site-header.component.spec`                    |

Service/mapper/guard/interceptor suites: `core/services/*.spec.ts` (12 — one
per route-group service incl. `api.service` and `llm-settings.service`),
`core/services/mappers/pull-request.mapper.spec`, `core/guards/role.guard.spec`,
`core/interceptors/{auth,error}.interceptor.spec`,
`core/services/auth-context.service.spec`, `environments/environment.spec`.

## Conventions (as enforced during the plan)

- **One service per backend route group** in `core/services/`, one model file
  per group in `core/models/`, snake_case → camelCase in the **one** mapper per
  group (`core/services/mappers/`) — components never reshape wire JSON.
- **Error contract**: 401 → re-login (auth interceptor retry → logout);
  403 → `/forbidden`; 404 → `/not-found` (except `…/scan-report`, which passes
  through as "no enrichment"); FastAPI `detail` kept on `ApiError` for inline
  422 field messages. Failed counts render `—`, never `0`.
- **Security**: server/LLM/scanner text is rendered as escaped text only (no
  `innerHTML`, no `bypassSecurityTrust*`); the LLM API key is write-only (the
  response carries `has_api_key` only; the field is cleared after load/save
  and omitted from payloads unless typed); effective roles come from the
  backend "me" profile, JWT re-derivation is only the route-guard fallback;
  tokens are never stored or logged (invite token excluded from analytics/error
  text).
- **Nav** is cosmetic (`AuthContextService.can()`); the backend re-authorizes
  every request (org access → uniform 404 when not a member).
- **Help** (redesign): `shared/help.copy.ts` is the single source of truth for
  `/help` and every `app-help-popover` — plain-text interpolation only; the two
  severity vocabularies (review comments `error|warning|suggestion|info` vs
  scan findings `critical|high|medium|low|info`) are reconciled explicitly in
  that copy.

---

## Verification status — v0.3.1 (previous release, plan Steps 11/12)

**Gates** — `format:check` clean, `lint` 0 errors (1 pre-existing warning in
`diff-view.component.ts`), `type-check` clean, `test:ci` **314 SUCCESS at the
Step 11 release → 338 after the Step 12 test-gap closure** (33 spec files),
production build OK (only pre-existing SCSS-budget / CommonJS warnings).

**Cluster** — frontend-only release: image
`127.0.0.1:5000/codesage/frontend:v0.3.1` (digest
`sha256:4d12def092db…`, registry tags `[v0.3.0, v0.3.1]`), `kubectl diff`
showed exactly the tag change, rollout complete (`1/1 Running`).
Backend/worker remain on `v0.3.0`; no postgres/redis/Keycloak manifests were
touched.

**Manual E2E table — PENDING** (deferred by decision at Step 11; test accounts
not provided). Planned checks, to run against the rolled-out UI:

| #   | Check                                                                          | Status  |
| --- | ------------------------------------------------------------------------------ | ------- |
| 1   | 4-role nav visibility (PA / ORG_ADMIN / REVIEWER / DEVELOPER) on all entries    | pending |
| 2   | Org-B member: org-B resources → uniform 404 page (never "no access" wording)    | pending |
| 3   | Staged review: summary edit, dismiss/restore, **double-click post → one post**  | pending |
| 4   | 409 "already posted" → toast + refresh                                          | pending |
| 5   | Verdict row (confirm / false positive / needs investigation) visible + saved    | pending |
| 6   | Ceiling violation on org settings → inline 422 error, save blocked              | pending |
| 7   | Invite lifecycle: create → console-mail link → accept → member (role visible)   | pending |
| 8   | Repository detail: reviews history loads (owner/name resolver)                  | pending |
| 9   | Stats bar (Step 2 Q1): shared `GET /reviews/{id}`, Comments/Open issues, `—`+retry | pending |
| 10  | Scan-report enrichment (Step 3): tools-failed banner, OWASP chips, fix hints    | pending |
| 11  | LLM key never displayed after save; precedence note matches backend behaviour   | pending |
| 12  | `/platform` read-only for PA, hidden (and 403'd) for everyone else              | pending |

---

## Verification status — v0.3.2 (UI-redesign release, redesign Steps 0–12)

**Gates** — `lint` 0/0, `type-check` clean, `format:check` clean,
`test:ci` **453 SUCCESS** (up from 338; +2 in the Step 10 a11y pass), production
build **449.01 kB raw / 125.53 kB transfer** (baseline before the redesign
436.79 / 121.71; same 9 pre-existing warnings — 8 component-style budgets +
js-sha256). One Conventional Commit per step, `b6f9eeb` … `docs: ui redesign`.

**Cluster** — frontend-only release: `kubectl diff` showed exactly the image
change (`frontend:v0.3.1` → `v0.3.2`), manifests applied with the
keycloak-db-init Job filter, rollout green with every other pod untouched;
smoke: `/` serves `main-HH5DOA56.js` (byte-identical to the local Step-10
build), `/help` and `/login` → 200, `/api/v1/health` → `healthy`,
`app-sidebar` marker present in the served bundle. Backend/worker remain on
`v0.3.0`.

**Responsive / visual captures** — `docs/ui/after/` (18 files): 6 public
screens (`index`, `login`, `not-found`, `forbidden`, `github-callback`,
`help`) × 1440×900 / 1024×768 / 390×844, chrome headless against the deployed
cluster — same method and viewports as `docs/ui/before/` (15 files, v0.3.1).
DOM-marker check confirms each URL renders its screen. **Authenticated
screens are still not capturable** (no test accounts — Q3) — they remain
covered only by the pending manual table above, which now applies to the
redesigned UI.
