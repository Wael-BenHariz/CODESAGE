# Frontend ↔ Backend API Coverage Matrix (v0.3.0)

Audit produced from the code itself: backend routes from
`backend/app/api/routes/*` + `backend/app/api/__init__.py` (verified against an
in-process `app.openapi()` dump — 59 operations), frontend services from
`frontend/src/app/core/services/*.ts`, screens from `app.routes.ts` and the
`features/` components that inject them.

**Legend (status column)**

| Status    | Meaning                                                                                                                 |
| --------- | ----------------------------------------------------------------------------------------------------------------------- |
| `done`    | A screen calls the endpoint with a path/shape the API actually serves.                                                  |
| `broken`  | The screen calls it, but the path or payload does not exist server-side → the call fails today (404 or shape mismatch). |
| `missing` | No screen calls it (dead service method, no UI, or a known gap).                                                        |
| `n/a`     | Not a UI endpoint (health probes, webhooks, FastAPI root).                                                              |

**Guard vocabulary** (from `app/security/roles.py` + `app/security/org_access.py`):
`public` → no auth; `any-auth` → `get_current_user` (any realm role, **incl. `NONE`**);
`DEVELOPER+` → `require_developer`; `PA` → `require_super_admin` (= `PLATFORM_ADMIN`);
`member` → org-membership row required (no membership → uniform **404**);
`ORG_ADMIN r/w` → `require_org_role(ORG_ADMIN, write=…)`; **no-PA-bypass** =
the PLATFORM_ADMIN read/settings carve-out does **not** apply to that route.

---

## 1. Backend endpoint inventory → frontend coverage

### Authentication (`/auth`) — 5

| Endpoint                           | Guard                      | Request → Response         | Frontend service method            | Screen                        | Status |
| ---------------------------------- | -------------------------- | -------------------------- | ---------------------------------- | ----------------------------- | ------ |
| `GET /auth/keycloak/config`        | public                     | → `{url, realm, clientId}` | `app.config.ts#initializeKeycloak` | bootstrap (APP_INITIALIZER)   | done   |
| `GET /auth/me`                     | any-auth                   | → `UserResponse`           | `AuthService.loadUser()`           | app-wide (headers, guards)    | done   |
| `POST /auth/logout`                | any-auth (optional bearer) | → 200                      | `AuthService.logout()`             | header menu                   | done   |
| `GET /auth/github/app/install-url` | any-auth                   | → `{url}`                  | `GithubService.getInstallUrl()`    | repository-list (Install CTA) | done   |
| `GET /auth/github/app/callback`    | public (`state` JWT)       | → redirect to SPA          | — (browser redirect target)        | `github-callback`             | done   |

### Users (`/users`) — 5

| Endpoint               | Guard    | Request → Response                 | Frontend service method               | Screen                 | Status  |
| ---------------------- | -------- | ---------------------------------- | ------------------------------------- | ---------------------- | ------- |
| `GET /users/me`        | any-auth | → `CurrentUser`                    | — (the UI uses `/auth/me`, same data) | —                      | missing |
| `PATCH /users/me`      | any-auth | `UserUpdate` → `UserResponse`      | `AuthService.updateProfile()`         | **no screen calls it** | missing |
| `DELETE /users/me`     | any-auth | → 204                              | —                                     | no account screen      | missing |
| `GET /users`           | PA       | page/per_page → `UserListResponse` | —                                     | — (Step 9)             | missing |
| `GET /users/{user_id}` | PA       | → `UserResponse`                   | —                                     | — (Step 9)             | missing |

### Repositories (`/repositories`) — 11

| Endpoint                                | Guard      | Request → Response                                      | Frontend service method                         | Screen                                                                    | Status  |
| --------------------------------------- | ---------- | ------------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------- | ------- |
| `GET /repositories`                     | any-auth   | page/per_page/enabled/search → `RepositoryListResponse` | `GithubService.getRepositories()`               | repository-list, dashboard                                                | done    |
| `GET /repositories/{id}`                | any-auth   | → `RepositoryResponse`                                  | —                                               | — (Step 2 resolver)                                                       | missing |
| `GET /repositories/{id}/detail`         | any-auth   | → `RepositoryDetail` (+`total_prs`, `total_reviews`)    | —                                               | — (Step 2)                                                                | missing |
| `PATCH /repositories/{id}`              | DEVELOPER+ | `RepositoryUpdate` → `RepositoryResponse`               | —                                               | no edit screen                                                            | missing |
| `POST /repositories/{id}/enable`        | DEVELOPER+ | → `RepositoryResponse`                                  | `GithubService.enableRepository()`              | repository-list, repository-detail                                        | done    |
| `POST /repositories/{id}/disable`       | DEVELOPER+ | → `RepositoryResponse`                                  | `GithubService.disableRepository()`             | repository-list, repository-detail                                        | done    |
| `DELETE /repositories/{id}`             | DEVELOPER+ | → 204                                                   | `GithubService.deleteRepository()`              | repository-list                                                           | done    |
| `POST /repositories/connect`            | DEVELOPER+ | `?github_repo_id=` → `RepositoryResponse` (201)         | `GithubService.connectRepository()`             | **no screen calls it** (selection goes through `/github/repos/selection`) | missing |
| `GET /repositories/github`              | any-auth   | → `GitHubRepoInfo[]`                                    | `GithubService.getGitHubRepositories()`         | **no screen calls it** (legacy)                                           | missing |
| `GET /repositories/install-url`         | any-auth   | → `{url}`                                               | — (duplicate of `/auth/github/app/install-url`) | —                                                                         | missing |
| `POST /repositories/installations/sync` | DEVELOPER+ | → sync response                                         | —                                               | no screen                                                                 | missing |

### GitHub App (`/github`) — 3

| Endpoint                       | Guard      | Request → Response          | Frontend service method             | Screen                                      | Status |
| ------------------------------ | ---------- | --------------------------- | ----------------------------------- | ------------------------------------------- | ------ |
| `GET /github/status`           | any-auth   | → `RepoStatusResponse`      | `GithubService.getInstallStatus()`  | dashboard, repository-list, github-callback | done   |
| `GET /github/repos`            | any-auth   | → `RepoResponse[]`          | `GithubService.getAppRepos()`       | repository-list (connect modal)             | done   |
| `POST /github/repos/selection` | DEVELOPER+ | `{repos, sync}` → `{saved}` | `GithubService.saveRepoSelection()` | repository-list                             | done   |

### Pull requests (`/pull-requests`) — 4

| Endpoint                                        | Guard                    | Request → Response                                                      | Frontend service method                            | Screen                  | Status     |
| ----------------------------------------------- | ------------------------ | ----------------------------------------------------------------------- | -------------------------------------------------- | ----------------------- | ---------- |
| `GET /pull-requests/repository/{repository_id}` | any-auth (repo 404)      | page/per_page/state/author → `PullRequestListResponse`                  | **called as `GET /repositories/{repoId}/pulls`**   | pr-list                 | **broken** |
| `GET /pull-requests/{pull_request_id}`          | member                   | → `PullRequestWithReviews` (`reviews_count`, `latest_review_id/status`) | **called as `GET /pulls/{owner}/{repo}/{number}`** | pr-detail               | **broken** |
| `POST /pull-requests/{id}/review`               | DEVELOPER+, member write | → `{review_id, status, message}`                                        | `GithubService.triggerReview()`                    | pr-detail, review-panel | done       |
| `GET /pull-requests/{id}/reviews`               | member                   | → `ReviewResponse[]` (newest first)                                     | `GithubService.getPullRequestReviews()`            | review-panel            | done       |

### Reviews (`/reviews`) — 13

| Endpoint                                      | Guard                                   | Request → Response                                                                                    | Frontend service method                 | Screen                     | Status  |
| --------------------------------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------- | --------------------------------------- | -------------------------- | ------- |
| `GET /reviews`                                | any-auth (org-scoped)                   | page/per_page/status_filter/pull_request_id → `ReviewListResponse`                                    | —                                       | — (Step 10 dashboard)      | missing |
| `GET /reviews/{id}`                           | member (PA bypass read)                 | → `ReviewWithComments` (+`viewer_role`)                                                               | `GithubService.getReviewDetail()`       | review-panel               | done    |
| `GET /reviews/{id}/scan-report`               | member (PA bypass read)                 | `?tool=&severity=` → `ScanReportResponse` (`tools_failed`, `findings[]` w/ `owasp`, `fix_suggestion`) | —                                       | — (Step 3)                 | missing |
| `GET /reviews/{id}/status`                    | member                                  | → `ReviewStatus` (`status`, `progress`)                                                               | `GithubService.getReviewStatus()`       | **no screen calls it**     | missing |
| `POST /reviews/{id}/retry`                    | DEVELOPER+, member write                | → review status                                                                                       | —                                       | no screen                  | missing |
| `DELETE /reviews/{id}`                        | DEVELOPER+, member write                | → 204                                                                                                 | —                                       | no screen                  | missing |
| `PATCH /reviews/{id}/comments/{cid}/resolve`  | DEVELOPER+, member write                | → comment                                                                                             | —                                       | no screen (legacy)         | missing |
| `PATCH /reviews/{id}/summary`                 | DEVELOPER+, member, **no PA bypass**    | `SummaryUpdate` (≤60 000 chars)                                                                       | `GithubService.updateReviewSummary()`   | review-panel (staged edit) | done    |
| `PATCH /reviews/{id}/comments/{cid}/dismiss`  | DEVELOPER+, member, **no PA bypass**    | → comment                                                                                             | `GithubService.dismissReviewComment()`  | review-panel               | done    |
| `PATCH /reviews/{id}/comments/{cid}/restore`  | DEVELOPER+, member, **no PA bypass**    | → comment                                                                                             | `GithubService.restoreReviewComment()`  | review-panel               | done    |
| `PATCH /reviews/{id}/comments/{cid}/validate` | **REVIEWER+**, member, **no PA bypass** | `ValidationCreate` → `CommentValidation`                                                              | `GithubService.validateReviewFinding()` | review-panel (verdict row) | done    |
| `POST /reviews/{id}/post`                     | DEVELOPER+, member, **no PA bypass**    | → `{github_review_id, posted_at}` (409 = already posted)                                              | `GithubService.postReview()`            | review-panel (post dialog) | done    |

### LLM settings (`/settings`) — 4

| Endpoint                  | Guard      | Request → Response                                     | Frontend service method                 | Screen   | Status |
| ------------------------- | ---------- | ------------------------------------------------------ | --------------------------------------- | -------- | ------ |
| `GET /settings/llm`       | any-auth   | → `LLMSettingsResponse` (never the key; `has_api_key`) | `LlmSettingsService.getLLMSettings()`   | settings | done   |
| `PUT /settings/llm`       | DEVELOPER+ | `{provider, model, api_key?, base_url?}`               | `LlmSettingsService.saveLLMSettings()`  | settings | done   |
| `DELETE /settings/llm`    | DEVELOPER+ | → cleared                                              | `LlmSettingsService.clearLLMSettings()` | settings | done   |
| `POST /settings/llm/test` | DEVELOPER+ | → `LLMTestResponse`                                    | `LlmSettingsService.testLLMSettings()`  | settings | done   |

### Organizations (`/orgs`) — 3

| Endpoint                      | Guard                                                   | Request → Response                                                        | Frontend service method                | Screen                                      | Status |
| ----------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------- | ------ |
| `GET /orgs`                   | any-auth (incl. NONE; PA sees all)                      | → `OrgSummary[]` (+own `role`)                                            | `OrgSettingsService.listOrgs()`        | settings, org-settings, RoleGuard elevation | done   |
| `GET /orgs/{org_id}/settings` | ORG_ADMIN r (PA bypass on read)                         | → `OrgSettingsResponse` (`overrides`/`effective`/`ceilings`/`overridden`) | `OrgSettingsService.getOrgSettings()`  | org-settings                                | done   |
| `PUT /orgs/{org_id}/settings` | ORG_ADMIN w (PA **no** bypass; absent=keep, null=reset) | `SettingsValues` → `OrgSettingsResponse`                                  | `OrgSettingsService.saveOrgSettings()` | org-settings                                | done   |

### Invitations (`/orgs/{id}/invitations` + `/invitations`) — 5

| Endpoint                                 | Guard                                          | Request → Response                                     | Frontend service method       | Screen          | Status |
| ---------------------------------------- | ---------------------------------------------- | ------------------------------------------------------ | ----------------------------- | --------------- | ------ |
| `POST /orgs/{org_id}/invitations`        | ORG_ADMIN w, **no PA bypass** (20/h/org → 429) | `InvitationCreate` → `InvitationOut` (never the token) | `InvitationService.create()`  | org-invitations | done   |
| `GET /orgs/{org_id}/invitations`         | ORG_ADMIN r (PA bypass ok)                     | → `InvitationOut[]`                                    | `InvitationService.list()`    | org-invitations | done   |
| `DELETE /orgs/{org_id}/invitations/{id}` | ORG_ADMIN w (PA bypass ok)                     | → 204                                                  | `InvitationService.revoke()`  | org-invitations | done   |
| `GET /invitations/{token}`               | **public**                                     | → `InvitationPreview` (org, role, masked email)        | `InvitationService.preview()` | invite-accept   | done   |
| `POST /invitations/{token}/accept`       | any-auth (NONE included)                       | → `InvitationAcceptResult` (409 = used)                | `InvitationService.accept()`  | invite-accept   | done   |

### Platform settings (`/platform`) — 2

| Endpoint                 | Guard | Request → Response                                                                       | Frontend service method                     | Screen                          | Status |
| ------------------------ | ----- | ---------------------------------------------------------------------------------------- | ------------------------------------------- | ------------------------------- | ------ |
| `GET /platform/settings` | PA    | → `PlatformSettingsResponse` (`defaults`, `effective_defaults`, `ceilings`, `hard_caps`) | `OrgSettingsService.getPlatformSettings()`  | org-settings (platform section) | done   |
| `PUT /platform/settings` | PA    | `{defaults?, ceilings?}` (absent=keep, null=reset)                                       | `OrgSettingsService.savePlatformSettings()` | org-settings (platform section) | done   |

### Non-UI (`n/a`) — 5

| Endpoint                                               | Guard                        | Notes                                  |
| ------------------------------------------------------ | ---------------------------- | -------------------------------------- |
| `GET /`                                                | public                       | FastAPI root banner.                   |
| `GET /health`, `GET /health/ready`, `GET /health/live` | public                       | K8s probes / ops.                      |
| `POST /webhooks/github`                                | HMAC (`X-Hub-Signature-256`) | GitHub → API, never called by the SPA. |

### Totals

| Status               | Count  |
| -------------------- | ------ |
| done                 | 34     |
| broken               | 2      |
| missing              | 18     |
| n/a                  | 5      |
| **total operations** | **59** |

---

## 2. Frontend calls to endpoints that do NOT exist

All four live in `core/services/github.service.ts`; **none of them can succeed
against v0.3.0**:

| #   | Frontend call                                                                                      | Caller screen             | Reality on the backend                                                          | Known?                         |
| --- | -------------------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------- | ------------------------------ |
| 1   | `GET /repositories/{owner}/{repo}` (`getRepository`)                                               | repository-detail         | No such path — only `/repositories/{id}` and `/repositories/{id}/detail` (UUID) | **yes** (AGENTS.md Known Gaps) |
| 2   | `GET /repositories/{repoId}/pulls` (`getPullRequests`) — and pr-list passes `owner/repo` as the id | pr-list                   | No such path — PRs live at `GET /pull-requests/repository/{repository_id}`      | **new**                        |
| 3   | `GET /pulls/{owner}/{repo}/{number}` (`getPullRequest`)                                            | pr-detail                 | No such path — `GET /pull-requests/{pull_request_id}` takes a UUID              | **new**                        |
| 4   | `GET /repositories/stats` (`getRepositoryStats`)                                                   | **no caller** (dead code) | No such path                                                                    | **new** (harmless today)       |

**Consequence:** repository detail, PR list and PR detail are all fully broken
today — the whole `repositories/:owner/:repo/**` subtree 404s. This is wider
than the single known gap in AGENTS.md.

### Shape bugs on endpoints that _do_ exist (path OK, payload mismatch)

These are typed `camelCase` models fed with raw `snake_case` JSON — no mapper:

| Method            | Returns (typed)                                                   | API actually returns                                                                                | Effect                                                  |
| ----------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `getPullRequests` | `PullRequest[]` (`repositoryId`, `author.login`, `baseBranch`, …) | `PullRequestListResponse` = `{items, total, …}` of `snake_case` PRs                                 | even with the right path, fields render empty/undefined |
| `getRepository`   | `Repository` (`fullName`, `defaultBranch`, …)                     | `RepositoryResponse` (`full_name`, `default_branch`, …) — `mapRepo()` exists but is **not** applied | `fullName` undefined                                    |
| `getReviewStatus` | `{status, progress}`                                              | `ReviewStatus` = `{review_id, status, progress, started_at, completed_at, error_message}`           | extra fields dropped (harmless), unused anyway          |

`getRepositories()` (list) is the only one that maps correctly (`mapRepo`).

---

## 3. Backend endpoints with no UI at all (candidates → `docs/BACKEND_GAPS_FOR_UI.md`)

Not all are _gaps_ — some are intentionally out of scope. Marked here for the
decision in Step 0/9:

| Endpoint / capability                                                 | Needed by                                                                                           | Verdict                                                                                                                                      |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Org members list** (`GET /orgs/{id}/members`)                       | Step 7 "members list (if an endpoint exists, otherwise record the gap)", Step 9 "show orgs/members" | **GAP — does not exist.** `GET /orgs` only returns the caller's own orgs+role; no endpoint enumerates an org's members.                      |
| **User update / suspend** (`PATCH /users/{id}`)                       | Step 9 "Read-only unless an update endpoint exists"                                                 | **GAP — does not exist** → Step 9 screen is read-only.                                                                                       |
| **Per-org review/repo metrics**                                       | Step 10 "per-org numbers for ORG_ADMIN"                                                             | **GAP.** `GET /reviews` is org-scoped as a whole but each `ReviewResponse` carries no org/repo field, so the UI cannot split counts per org. |
| `GET /users/me`                                                       | —                                                                                                   | Exists but duplicates `/auth/me`; no screen needed.                                                                                          |
| `POST /reviews/{id}/retry`, `DELETE /reviews/{id}`, `PATCH …/resolve` | —                                                                                                   | Exist; no screen yet (optional — not required by the plan).                                                                                  |
| `GET /reviews/{id}/status`                                            | in-flight progress polling                                                                          | Exists; screen unused (panel refetches the review instead).                                                                                  |

---

## 4. What already exists in the UI (do NOT rebuild)

Checked for Step 0 of the plan:

| Planned screen          | State                                                                                                                                                                                                                                                | Where                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **Review panel**        | ✅ exists (Step 7b of the release plan) — summary (`edited_summary` wins), status states, findings grouped by file (severity→file→line), tool badge + `also_detected_by`, rule id, CWE, snippet, escaped rendering everywhere (no `innerHTML`).      | `features/pull-requests/review-panel/`                          |
| **Staged controls**     | ✅ exists — post dialog w/ counts, summary edit + 60 000-char cap, dismiss/restore (optimistic + rollback), 409 → "already posted" + refresh, controls read-only once posted.                                                                        | same component                                                  |
| **Reviewer action row** | ✅ exists — confirm / false positive / needs investigation / severity override / note; upsert with rollback; gated on `viewer_role` ≥ REVIEWER; verdicts shown to everyone.                                                                          | same component                                                  |
| **Org settings**        | ✅ exists (726-line component) — 10 fields, effective vs override, ceilings next to numerics, per-field reset, platform defaults + ceilings sections for PA, inline 422 per field.                                                                   | `features/settings/org-settings/`                               |
| **Invitations**         | ✅ exists — invite form (email + DEVELOPER/REVIEWER), pending list, revoke, status badges.                                                                                                                                                           | `features/settings/org-invitations/` (embedded in org settings) |
| **Accept page**         | ✅ exists — public `/invite/accept?token=…`, preview, mismatch warning, never auto-accepts, sign-in returns to same URL.                                                                                                                             | `features/invitations/invite-accept/`                           |
| **Role-aware nav**      | ⚠️ partial — `navVisibility()` gates entries, but every page rolls its own `<nav>` (dashboard: Dashboard/Repositories/Settings only); there is **no shared header/nav component**, and no nav entry for org settings, platform/users or invitations. | per-component templates                                         |

Other things that exist and must be reused, not duplicated:

- `ApiService` + `ApiError` (keeps FastAPI `detail` for inline 422s) — `core/services/api.service.ts`
- `AuthInterceptor` (401 → forced `updateToken(-1)` retry → logout) — `core/interceptors/auth.interceptor.ts`
- `RoleGuard` + `deriveRole()` mirroring `security/roles.py` (incl. `NONE`, compat map, broker DEVELOPER fallback) + `GET /orgs` elevation for admin routes — `core/guards/role.guard.ts`
- Shared `loading` / `error` / `avatar` components — `shared/components/`
- `AuthService` (GET `/auth/me`, localStorage profile cache — profile only, **no tokens stored**)

**Not present yet (Step 1 work):** global 403/404 pages, an error interceptor
for non-401 statuses, a toast/snackbar service, an `AuthContextService` with
`can(action)` helpers and an org switcher, and a shared role-aware nav.

---

## 5. Contradictions / decisions needed before building

1. **Scope of Step 2.** The plan only names the repository-detail 404, but PR
   list and PR detail are broken by the same class of bug (§2 #2, #3), i.e. the
   screens Step 3 builds on. _Proposal:_ fix all three phantom paths (plus the
   `mapRepo`-style mappers) inside the Step 2 commit, since Step 3 must then
   verify against a working PR detail page.
2. **Step 3 is a completion, not a greenfield.** The review panel exists but
   never calls `GET /reviews/{id}/scan-report`, so it currently cannot show:
   `tools_failed` (sonar/semgrep unavailable header), OWASP tags,
   `fix_suggestion`, or scan findings that never became comments.
   _Proposal:_ add the scan-report enrichment to the existing panel.
3. **Steps 4/5/6/7 screens already exist** — they will be audited against the
   plan's checklist and only deltas fixed (no parallel duplicate screens).
4. **`GET /orgs/{id}/members` does not exist** (Step 7/9) → members list goes
   to `docs/BACKEND_GAPS_FOR_UI.md`; invitations remain the only membership
   surface.
5. **LLM precedence wording (Step 8)** must be confirmed before it is written
   into the UI — the code rule is documented in `docs/BACKEND_GAPS_FOR_UI.md`
   §"LLM precedence" pending sign-off (per-user model → org `ai_model` →
   system default; provider is never overridden by the org; org `ai_model`
   only reaches a review when the installation owner has personal LLM
   credentials configured).
