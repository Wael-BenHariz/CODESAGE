# Plan: Roles, Org Settings, Staged Reviews, Invitations (v0.3.0)

Branch: `feat/roles-org-settings-staged-reviews` (from `feat/semgrep-integration`,
which contains the finished Semgrep work — release `v0.2.1-semgrep`, HEAD `9cd4b85`).

Status: **Step 0 (recon) done. Open questions in §5 must be answered before Step 1.**

---

## 1. Recon map (what actually exists)

### 1.1 Auth / roles

| Piece | Location | Facts |
|---|---|---|
| Role derivation | `backend/app/security/roles.py` | `derive_role(token_roles, via_github)` — precedence **SUPER_ADMIN > GUEST > DEVELOPER**; no recognized role → `DEVELOPER` if `via_github` (token carries `githubId`/`githubLogin`), else **GUEST (fail-closed, read-only)**. Token with no role claim at all → 401 in `_claim_roles`. |
| Guards | same file | `require_role(*allowed)` factory; shorthands `require_developer = require_role(SUPER_ADMIN, DEVELOPER)`, `require_super_admin = require_role(SUPER_ADMIN)`. `require_admin` in `dependencies.py` (legacy, checks `SUPER_ADMIN` literally). |
| Token→DB sync | `backend/app/security/dependencies.py` | `get_current_user` validates RS256/JWKS token, JIT-provisions `users` row, **re-derives role from the JWT on every request** (DB `users.role` is only a mirror; guards never trust it). |
| Keycloak realm JSON | `infrastructure/k8s/base/keycloak/keycloak-configmap.yaml` (ConfigMap `keycloak-realm`, key `codesage-realm.json`) | **Not a standalone file.** Imported by the `--import-realm` flag only on a fresh/empty Keycloak DB; an init container renders `${GITHUB_CLIENT_ID}` placeholders. Realm roles: `SUPER_ADMIN`, `DEVELOPER`, `GUEST`. Groups: `super-admins`, `developers`, `guests` (each mapped to its realm role). |
| Route guards in use | `routes/*.py` | reads → `get_current_user` (any authenticated role); mutations → `require_developer`; `/users` → `require_super_admin`. Enforced by `tests/test_route_inventory.py` (every route must carry an auth dependency or be allow-listed). |
| Test harness | `backend/tests/conftest.py` | `make_keycloak_token(roles=(...))` mints RS256 tokens with a throwaway key; `mock_jwks` fixture serves the matching JWKS. `roles=("DEVELOPER",)` default. |
| Frontend | `frontend/src/app/core/guards/role.guard.ts` | `deriveRole()` mirrors backend (same precedence + fallbacks). `RoleGuard` reads `route.data.roles`; unauthenticated → `/login?returnUrl=…`; wrong role → `/repositories`. |
| Frontend routes | `frontend/src/app/app.routes.ts` | `ANY_ROLE = ['DEVELOPER','GUEST','SUPER_ADMIN']` (reads), `WRITE_ROLES = ['DEVELOPER','SUPER_ADMIN']` (dashboard, settings). |

**Current role names**: `SUPER_ADMIN`, `DEVELOPER`, `GUEST`.
Precedence: `SUPER_ADMIN > GUEST > DEVELOPER` (GUEST deliberately outranks DEVELOPER
so an explicit read-only downgrade wins over a default role).

### 1.2 Models / data chain

```
users ──< oauth_tokens
users ──< watched_repos >── repositories ── github_installations (account_login, account_type user|organization)
users ──< reviews >── pull_requests >── repositories
reviews ──< review_comments (severity, category, resolved, suggestion, github_comment_id)
reviews ──< scan_reports >── scan_findings (migrations 010/011)
github_installations  ←  users.github_installation_id (migration 002)
repo_tenants (migration 009, schema owned by repo-tenant-service)
```

- **There is no `orgs`, no `org_members`, no `org_id` anywhere** (grep over
  `backend/app` = 0 hits). The closest tenancy concept is
  `github_installations.account_login/account_type` plus the per-user
  `users.github_installation_id` link. Multi-tenancy in the k8s sense is
  *repo → namespace* (`repo-tenant-service`), not org → members.
- `reviews.github_review_id` **already exists** (migration 006).
- `review_comments` already has `resolved/resolved_at` (a different concept from
  the `dismissed` flag planned in Step 6).
- `users.role` is the only stored role string today (mirror of the JWT).

### 1.3 Worker pipeline & GitHub posting

- Queue: BullMQ (`BULLMQ_REVIEW_QUEUE=review-requests`, `BULLMQ_CONCURRENCY=5`),
  `backend/app/workers/main.py` → `review_queue.py` → `review_processor.py`.
- `process_review_job()`: idempotency guard (`status != "pending"` → skip) →
  installation-token PR file fetch → SonarQube + Semgrep in parallel →
  persist scan report → `ReviewContext` → `ReviewOrchestrator.run()` →
  **post ONE summary review to GitHub** → store rows → `completed`.
- **Posting code**: `post_pr_review()` in `backend/app/workers/review_processor.py`
  (line 42), called at line 319. Body = **the LLM summary prose only**
  (`event: COMMENT`, no inline comments). `ReviewComment.github_comment_id` is
  never written — individual findings are **not** posted to GitHub today.
- 404 on post → finishes gracefully with a note; 422 → logs body and fails.
- Review statuses used: `pending | processing | completed | failed`
  (`pull_requests.py` `latest_review_status`, frontend `pr-detail` renders them).

### 1.4 Frontend surfaces

- **No shared nav component** — the nav links live inline in
  `dashboard.component.html` (Dashboard / Repositories / Settings); other pages
  have their own headers. Role-based *route* guards exist; nothing currently
  hides nav entries by role.
- **The PR detail page shows no review content at all**: `pr-detail.component.html`
  renders PR metadata, stats (from `reviewStatus`) and a diff placeholder — no
  summary, no findings/comments list. There is no component anywhere that
  renders `ReviewWithComments`.
- `github.service.ts` talks to `/reviews/{id}/status`, `/pull-requests/*`; there
  is no service method for review detail, summary editing, dismiss, validate or post.
- Settings page exists (`features/settings`) but only per-user LLM settings.
- `keycloak-angular` + `keycloak-js` 24; `RoleGuard` extends `KeycloakAuthGuard`
  (`this.roles` = realm roles from `tokenParsed`).

### 1.5 Existing config constants (ceilings candidates)

| Constant | Value | Where |
|---|---|---|
| `LLM_DIFF_CHAR_CAP` | 16000 | `config.py` — applied in `review_processor.py:214` |
| `DIFF_MAX_CHARS` | 100 000 | hard cap in `review_processor.py:28` (build stage) |
| `MAX_FINDINGS_PER_AGENT` | 15 | module constant `agents/specialist_agents.py:41` (not settings-driven) |
| `BULLMQ_CONCURRENCY` | 5 | `config.py` — worker-wide, no per-org limit |
| `AGENT_*_TEMPERATURE`, `AGENT_ORCHESTRATOR_MAX_TOKENS` | — | `config.py` |
| `SEMGREP_ENABLED` | true | `config.py` — global scanner switch |
| `SONARQUBE_*` | — | `config.py` (URL/token/timeout/prefix) |

No audit-log table/mechanism exists (`webhook_events` is the only "audit" trail,
and it is webhook-only). No email/SMTP configuration exists anywhere
(`config.py`, `.env.example`, k8s secrets).

### 1.6 Baseline verification

- Backend: `206 passed, 5 skipped` (local Postgres 16 + Redis 7 test containers).
- Frontend: `npm run test:ci / lint / type-check / format:check` available; node 26, deps installed.
- Cluster: k3s live, `codesage` namespace pods Running (backend, worker, frontend,
  keycloak, postgres, redis, repo-tenant-service, semgrep-service).
- Local registry `127.0.0.1:5000` already holds `codesage/{backend,worker}:v0.2.1-semgrep`.

---

## 2. Current role names → target

| Today (JWT + DB) | Target | Keycloak group (new) |
|---|---|---|
| `SUPER_ADMIN` | `PLATFORM_ADMIN` | `platform-admins` |
| — (new) | `ORG_ADMIN` | `org-admins` |
| — (new) | `REVIEWER` | `reviewers` |
| `DEVELOPER` | `DEVELOPER` | `developers` (exists) |
| `GUEST` | → `developers` per prompt migration (never → reviewers) | legacy `guests` group kept |

New precedence: `PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER`
(REVIEWER inherits DEVELOPER's capabilities).

---

## 3. Design sketch per step

- **Step 1 (backend roles)** — rewrite `roles.py` constants + `derive_role`
  precedence; compatibility map for old names (`SUPER_ADMIN→PLATFORM_ADMIN`,
  `GUEST→…`, see Q4); `require_role` validates against the new set;
  `require_developer`/`require_super_admin` rebuilt on top of the new ladder
  (add `require_org_admin`/`require_reviewer` shorthands). Realm JSON in the
  ConfigMap gains the four new roles/groups (old ones kept). New idempotent
  `scripts/keycloak_migrate_roles.sh` (admin REST via `kcadm.sh` inside the
  keycloak pod; `--dry-run` prints the plan): create groups, move members
  SUPER_ADMIN→platform-admins, DEVELOPER→developers, GUEST→developers, keep
  old groups. Data migration `012`: `UPDATE users SET role = …` with the same
  mapping, reversible downgrade. Tests: precedence, compat map, one guard test
  per role.
- **Step 2 (frontend roles)** — mirror `deriveRole()` + precedence + compat map;
  update `ANY_ROLE`/`WRITE_ROLES` to the four names; guard unit tests; hide nav
  entries (needs a role-aware nav helper — nav is inline per page today).
- **Step 3 (org settings backend)** — new `org_settings` + `platform_settings`
  tables (all nullable = use global default), `resolve_org_settings(org_id)` as
  the single merge point with ceiling clamping, `GET/PUT /orgs/{id}/settings`
  and `GET/PUT /platform/settings`, pydantic validation (422 above ceiling),
  structured audit logs. **Blocked on Q1 (org model).**
- **Step 4 (worker)** — call `resolve_org_settings` at job start; thread
  effective values into diff cap, findings cap (make `MAX_FINDINGS_PER_AGENT`
  a parameter of `format_findings`), agent enable-list, scanner flags,
  triggers, min-severity; per-org Redis semaphore acquired/released in
  `finally`; structured log of effective settings (no secrets).
- **Step 5 (settings UI)** — ORG_ADMIN settings form + PLATFORM_ADMIN section,
  ceilings displayed, per-field reset, inline API errors. **Blocked on Q1.**
- **Step 6 (staged data model)** — migration `013`: `reviews.posting_mode`
  (default `auto`), `reviews.posted_at`, `reviews.edited_summary`
  (`github_review_id` already exists); `review_comments.dismissed/dismissed_by/dismissed_at`.
  Extract `post_review_to_github(review)` used by worker (auto) and API (staged).
  New status `ready_to_post` must be handled by `pull_requests.py`
  (`latest_review_status`), the status endpoint and frontend rendering
  (frontend just prints the raw status string — verify + test).
- **Step 7 (staged API)** — `PATCH /reviews/{id}/summary`,
  `PATCH /reviews/comments/{id}/dismiss|restore`, `POST /reviews/{id}/post`
  (prompt's paths differ from the existing
  `/reviews/{rid}/comments/{cid}/resolve` style — see N7). Row lock via
  `SELECT … FOR UPDATE` + conditional status update for idempotency; 409 on
  double post; GitHub failure → `posted_at` stays null, 502 with retryable detail.
- **Step 8 (staged UI)** — **prerequisite: build the review display panel on the
  PR detail page** (summary + findings list — none exists today, see Q2), then
  the staged banner, editable summary, dismiss/restore controls, posted state.
- **Step 9 (validation backend)** — `review_finding_validations` table with
  unique `(comment_id, reviewer_id)` upsert, `PATCH /reviews/comments/{id}/validate`,
  latest verdicts included in review detail response. Plain-text notes stored as-is.
- **Step 10 (validation UI)** — reviewer action row under each finding
  (ReviewER+ only), verdict list visible to everyone in the org, optimistic
  update + rollback. **Blocked on Q1 (org membership) + Q2 (findings UI).**
- **Step 11 (invitations)** — `org_invitations` table (SHA-256 of a 32-byte
  urlsafe token, 7-day expiry, statuses), pluggable mail sender with a
  console/log dev implementation (no mail mechanism exists — SMTP config to be
  added: `SMTP_HOST/PORT/USER/PASSWORD/FROM/TLS`), per-org invite rate limit,
  public masked-token lookup with uniform responses, single-transaction accept
  with `ON CONFLICT` upsert and role floor (never downgrade), revoke + list
  endpoints. **Blocked on Q1.**
- **Step 12 (invitations UI)** — invite form + pending list for ORG_ADMIN;
  `/invite/accept?token=…` page with check-sso, mismatch warning, explicit
  accept click, token kept out of logs/analytics. **Blocked on Q1.**
- **Step 13 (release)** — `TAG=v0.3.0`, build/push three images, manifest tag
  bump (only backend/worker/frontend — never postgres/redis/keycloak/PVCs),
  `kubectl diff` shown first, Alembic through the normal init mechanism with
  logs shown, `keycloak_migrate_roles.sh --dry-run` → wait for OK, rollout
  status + pods/logs, verification table + repeatable scripts in repo.
- **Step 14 (docs)** — role matrix, settings table (defaults + ceilings),
  staged sequence diagram, invitation flow, Keycloak migration script, TAG
  rebuild/deploy runbook.

---

## 4. Notes resolved by following the prompt or the code (no decision needed)

- **N1**: `reviews.github_review_id` already exists (migration 006) — Step 6's
  migration only adds `posting_mode`, `posted_at`, `edited_summary` and the
  three `review_comments` dismiss columns.
- **N2**: "Realm JSON" = the ConfigMap
  `infrastructure/k8s/base/keycloak/keycloak-configmap.yaml`. Editing it affects
  **fresh installs only** (`--import-realm` skips an initialized DB) — which is
  exactly why the live migration script is required.
- **N3**: No audit mechanism exists → Step 3 uses structured logs, as the
  prompt allows.
- **N4**: No mail mechanism exists → Step 11 adds a pluggable sender with a
  console/log implementation (prompt's fallback). SMTP config to be provided
  later: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
  `SMTP_FROM`, `SMTP_TLS` (none present today).
- **N5**: GUEST group members are explicitly migrated to `developers` (never
  reviewers), per prompt. Note the consequence: **legacy guests gain DEVELOPER
  write access** once migrated — accepted as instructed.
- **N6**: `repository → org` scoping today is effectively
  `repository → github_installation` (via `installation_id`), and user access
  is `_ensure_installation_accessible_to_user` / `account_id == github_id`
  checks in `repositories.py` — the org chain for rule 5 will be built on
  whatever Q1 decides.
- **N7**: Step 7 paths (`/reviews/comments/{id}/…`) differ from the existing
  nested style (`/reviews/{rid}/comments/{cid}/resolve`). The prompt is
  explicit, so the new endpoints use the prompt's paths; the existing resolve
  endpoint stays untouched.
- **N8**: Postgres/Redis for tests run in **local Docker containers**
  (`codesage_test`, Redis db 15), never against the in-cluster databases.
  Step 13's Alembic run goes through the project's normal init mechanism only.

---

## 5. Open questions (contradictions between the prompt and the code — awaiting your decision)

### Q1 — There is no org model (BLOCKER for Steps 3, 5, 9–12 and rule 5)

Rule 5 and Steps 3/5/9/10/11/12 require `orgs`, `org_members` and a
review → repo → org chain. **None of these tables exist**; the only tenancy
signal is `github_installations (account_login, account_type)` and the
per-user `users.github_installation_id` link. Options:

- **A (recommended): first-class orgs seeded from GitHub installations.**
  Create `orgs` (name = `account_login`, unique) + `org_members (user_id,
  org_id, role)`; migration seeds one org per distinct installation account
  with auto-members = users whose `github_installation_id` matches (keeps the
  rule-5 chain: review → pull_request → repository → installation → org).
  Invitations (Step 11) then insert into `org_members`. Downside: auto-members
  inherit org membership implicitly.
- **B: `org` = `github_installation` (no new orgs table).** Membership tracked
  in a new `org_members (user_id, installation_id, role)`. Cheap, but invites
  and org naming get awkward (user vs organization accounts).
- **C: minimal synthetic org** (one "default" org everyone belongs to). Lets
  all steps ship but multi-org isolation (rule 5 tests) becomes vacuous.

### Q2 — The PR detail page has no review/findings UI (scope for Steps 8/10)

Steps 8 and 10 assume findings and a summary are already rendered on the PR
detail page. Today only PR metadata + stats are shown; no component renders
`ReviewWithComments`. Plan: build a minimal review panel (summary + findings
list with severity/file/line) as part of Step 8, then layer the staged
controls on it; Step 10 adds the reviewer action row underneath each finding.
Confirm this scope, or tell me the review UI lives somewhere else.

### Q3 — What exactly gets posted to GitHub (affects "dismissed findings are excluded")

Today `post_pr_review` posts **only the LLM summary prose** — findings are
stored in the DB but never posted. "Dismissed findings excluded from the post"
therefore implies the posted body must contain findings. Options:

- **A (recommended): post body = (edited_)summary + a "Findings" section
  rendered from non-dismissed comments** — in *both* modes. Consequence: the
  auto-mode body gains a findings appendix (the flow is unchanged: still
  posted immediately), so the "auto path unchanged" test asserts the flow, not
  byte-identical bodies.
- **B: auto keeps summary-only; staged posts summary + non-dismissed findings.**
  Byte-identical auto body, but the two modes post different content shapes.
- **C: keep summary-only everywhere; dismissals only affect UI counts.**
  Then "dismissed findings excluded from the post" is untestable — not
  recommended.

### Q4 — Fail-closed fallback + legacy `GUEST` tokens

The new ladder's lowest role (`DEVELOPER`) is a **write** role; the current
fail-closed fallback is read-only `GUEST`. Two sub-decisions:

1. **Compat map for tokens carrying `GUEST`** (must keep working for one
   release): map to `DEVELOPER` (consistent with the GUEST→developers group
   migration; grants write to old guests), or map to a legacy read-only
   fallback (preserves current semantics; guests become developers only after
   their token is re-issued — within minutes anyway, token lifespan is 300 s)?
2. **Fallback for a non-GitHub token with no recognized role** (only
   `default-roles-*` — currently read-only GUEST): map to `DEVELOPER`
   (fail-open), 401 (fail-closed by rejection — could lock out existing
   console-only users), or keep an **internal read-only legacy fallback**
   (not one of the four roles; frontend mirrors it) that preserves today's
   exact security posture for one release?

Recommendation: **legacy `GUEST` tokens → `DEVELOPER` (1a)** to match your
group migration, **unrecognized non-GitHub tokens → internal read-only legacy
fallback (2c)** so nothing that is read-only today silently gains write access.
