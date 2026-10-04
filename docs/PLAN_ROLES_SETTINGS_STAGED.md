# Plan: Roles, Org Settings, Staged Reviews, Invitations (v0.3.0)

Branch: `feat/roles-org-settings-staged-reviews` (from `feat/semgrep-integration`,
which contains the finished Semgrep work — release `v0.2.1-semgrep`, HEAD `9cd4b85`;
**not merged into `main`**).

Status: **Step 0 (recon) done; §5 decisions resolved, §6 flags open (non-blocking —
confirm before/during Step 1). Ready for Step 1.**

---

## 1. Recon map (what actually exists)

### 1.1 Auth / roles

| Piece | Location | Facts |
|---|---|---|
| Role derivation | `backend/app/security/roles.py` | `derive_role(token_roles, via_github)` — precedence **SUPER_ADMIN > GUEST > DEVELOPER**; no recognized role → `DEVELOPER` if `via_github` (token carries `githubId`/`githubLogin`), else **GUEST (fail-closed, read-only)**. Token with no role claim at all → 401 in `_claim_roles` (hardened, tested by `test_token_hardening.py`). |
| Guards | same file | `require_role(*allowed)` factory; shorthands `require_developer = require_role(SUPER_ADMIN, DEVELOPER)`, `require_super_admin = require_role(SUPER_ADMIN)`; `require_admin` in `dependencies.py` (legacy literal check). |
| Token→DB sync | `backend/app/security/dependencies.py` | `get_current_user` validates RS256/JWKS, JIT-provisions `users`, **re-derives role from the JWT on every request** (DB `users.role` is a mirror; guards never trust it). `_sync_profile_and_role` writes the mirror. |
| Keycloak realm JSON | `infrastructure/k8s/base/keycloak/keycloak-configmap.yaml` (ConfigMap `keycloak-realm`, key `codesage-realm.json`) | **Not a standalone file.** `--import-realm` imports only against an empty Keycloak DB; an init container renders `${GITHUB_CLIENT_ID}` placeholders. Realm roles: `SUPER_ADMIN`, `DEVELOPER`, `GUEST`. Groups: `super-admins`, `developers`, `guests`. **No `defaultRoles`, no auto-group assignment** — only the bootstrap admin user is in `/super-admins`. A fresh GitHub-broker user gets NO realm role (relevant to F1). |
| Route guards in use | `routes/*.py` | reads → `get_current_user`; mutations → `require_developer`; `/users` → `require_super_admin`. `tests/test_route_inventory.py` forces every route to carry an auth dependency or be allow-listed (the public `GET /invitations/{token}` must be added to that allow-list in Step 11). |
| Test harness | `backend/tests/conftest.py` | `make_keycloak_token(roles=(...))` mints RS256 tokens; `mock_jwks` serves the matching JWKS; DB schema via `Base.metadata.create_all` (tests do not run Alembic); local Postgres `codesage_test` + Redis db 15. |
| Frontend | `frontend/src/app/core/guards/role.guard.ts` | `deriveRole()` mirrors backend incl. `viaGitHub` fallback; `RoleGuard` reads `route.data.roles`; unauthenticated → `/login?returnUrl`; wrong role → `/repositories`. |
| Frontend routes | `frontend/src/app/app.routes.ts` | `ANY_ROLE = ['DEVELOPER','GUEST','SUPER_ADMIN']`, `WRITE_ROLES = ['DEVELOPER','SUPER_ADMIN']` (dashboard, settings). |

### 1.2 Models / data chain

```
users ──< oauth_tokens
users ──< watched_repos >── repositories ── github_installations (account_login, account_type user|organization)
users ──< reviews >── pull_requests >── repositories
reviews ──< review_comments (severity info|warning|error|suggestion, category, resolved, suggestion, github_comment_id)
reviews ──< scan_reports >── scan_findings (NormalizedFinding: tool, rule_id, cwe, line_start/end, snippet, also_detected_by)
github_installations  ←  users.github_installation_id (migration 002)
repo_tenants (migration 009, schema owned by repo-tenant-service)
```

- **No `orgs` / `org_members` / `org_id` anywhere** (pre-recon grep = 0 hits). See §5-Q1.
- `reviews.github_review_id` **already exists** (migration 006).
- `review_comments.resolved/resolved_at` already exists — a different concept from the
  `dismissed*` columns planned in Step 6 (keep both; `resolved` stays untouched).
- Uninstall (`webhooks.py`, action `deleted`) **deletes** the `github_installations`
  row and cascades repositories → pull_requests → reviews. Org rows and memberships
  must survive this (see Q1 design).
- Installation creation points (org provisioning hooks): `webhooks.py:523`
  (`_upsert_installation_record`) and `repositories.py:232` (installations sync);
  user↔installation link writes: signed-state install callback (`repositories.py:92`)
  and JIT adoption (`dependencies.py::_adopt_github_installation`).
- `AgentComment` (specialist output) has **no** tool/rule_id/cwe — the LLM schema does
  not echo source-finding metadata (see Step 7b enrichment design).

### 1.3 Worker pipeline & GitHub posting

- BullMQ (`BULLMQ_REVIEW_QUEUE=review-requests`, `BULLMQ_CONCURRENCY=5`):
  `workers/main.py` → `review_queue.py` → `review_processor.py::process_review_job`.
- Pipeline: idempotency guard (`status != "pending"` → skip) → installation-token PR
  file fetch → SonarQube + Semgrep in parallel → persist scan report → `ReviewContext`
  → `ReviewOrchestrator.run()` → **post ONE summary review to GitHub** → store rows →
  `completed`.
- **Posting**: `post_pr_review()` (`review_processor.py:42`, called at :319) —
  body = **LLM summary prose only**, `event: COMMENT`, no inline comments.
  `ReviewComment.github_comment_id` is never written; findings are not posted today.
  404 → graceful note; 422 → logged + failed.
- Review statuses: `pending | processing | completed | failed`
  (`pull_requests.py::latest_review_status`, frontend renders the raw string —
  must tolerate the new `ready_to_post`).
- Review creation: webhook (`webhooks.py:304`, event-driven) and manual
  `POST /pull-requests/{pull_request_id}/review` (sets `user_id`, `require_developer`).

### 1.4 Frontend surfaces

- **No shared nav component** — nav links are inline in `dashboard.component.html`
  (Dashboard / Repositories / Settings); other pages have their own headers.
- **The PR detail page shows no review content** — `pr-detail.component.html` renders
  PR metadata, stats and a diff placeholder; no component anywhere renders
  `ReviewWithComments`. See §5-Q2 (new Step 7b).
- `github.service.ts` has `/reviews/{id}/status` + `/pull-requests/*` only; no service
  methods for review detail, summary editing, dismiss, validate or post.
- Settings page exists (`features/settings`) — per-user LLM settings only.
- `keycloak-angular` + `keycloak-js` 24; token roles via `tokenParsed.realm_access.roles`.

### 1.5 Existing config constants (settings candidates)

| Constant | Value | Where |
|---|---|---|
| `LLM_DIFF_CHAR_CAP` | 16000 | `config.py`; applied `review_processor.py:214` |
| `DIFF_MAX_CHARS` | 100 000 | hard build-stage cap `review_processor.py:28` |
| `MAX_FINDINGS_PER_AGENT` | 15 | module constant `agents/specialist_agents.py:41` |
| `BULLMQ_CONCURRENCY` | 5 | `config.py`, worker-wide, no per-org limit |
| `SEMGREP_ENABLED` | true | `config.py` (SonarQube has no enable flag today) |
| `AGENT_*_TEMPERATURE`, `AGENT_ORCHESTRATOR_MAX_TOKENS` | — | `config.py` |

No audit mechanism (only `webhook_events`). No email/SMTP config anywhere
(`config.py`, `.env.example`, k8s secrets) — see N4.

### 1.6 Baseline verification

- Backend: `206 passed, 5 skipped` on local Docker Postgres 16 + Redis 7
  (`cs-test-pg` / `cs-test-redis`; the in-cluster DBs are never used for tests).
- Frontend: `npm run test:ci / lint / type-check / format:check` available; node 26, deps installed.
- Cluster: k3s live; `codesage` pods Running (backend, worker, frontend, keycloak,
  postgres, redis, repo-tenant-service, semgrep-service).
- Local registry `127.0.0.1:5000` holds `codesage/{backend,worker}:v0.2.1-semgrep`.

---

## 2. Current role names → target

| Today (JWT + DB) | Target | Keycloak group (new) |
|---|---|---|
| `SUPER_ADMIN` | `PLATFORM_ADMIN` | `platform-admins` (new) |
| — (new) | `ORG_ADMIN` | `org-admins` (new) |
| — (new) | `REVIEWER` | `reviewers` (new) |
| `DEVELOPER` | `DEVELOPER` | `developers` (exists) |
| `GUEST` | **no group migration** — left in `guests`, printed for manual assignment | legacy `guests` (kept) |
| — (internal) | `NONE` — sentinel, read-only, not assignable, not in `org_members`, not a group | — |

Ladder: `PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER` (REVIEWER inherits
DEVELOPER). `NONE` has **no ladder position**.

**Capability model (used by every new endpoint guard):**

1. `NONE` (global role) on a **write** endpoint → **403 immediately** — unconditionally
   read-only, membership cannot rescue it (test: *NONE gets 403 on every write endpoint*).
2. Membership: caller must have an `org_members` row for the resource's org —
   otherwise **404** (test: *no org_members row → 404 regardless of role*).
   **`PLATFORM_ADMIN` bypasses membership** (flag F2) — required by Step 3's
   "ORG_ADMIN of that org **or PLATFORM_ADMIN**".
3. Effective role = `max(global JWT role, org_members.role)`; if below the endpoint's
   required role → **403** (test: *DEVELOPER gets 403 on validate*).

Reading order consequence: cross-org (step 2 fails) yields 404 **before** any role
403 for DEVELOPER+ callers, and NONE hits step 1 first on writes — satisfying both
stated tests. Existing non-org endpoints keep today's guards unchanged
(`require_developer` excludes `NONE` automatically — 403 parity with old GUEST).

**`derive_role` per Q4 (strict reading — flag F1):**
- Map claims through the one-release compat map: `SUPER_ADMIN → PLATFORM_ADMIN`,
  `GUEST → NONE`, `DEVELOPER → DEVELOPER`, new names pass through; then ladder;
  a mapped `NONE` present in the claim set **wins over `DEVELOPER`** (preserves today's
  "explicit GUEST downgrade outranks DEVELOPER").
- Unrecognized or empty role claims → `NONE`. **Never default to `DEVELOPER`** —
  the `via_github` DEVELOPER fallback is removed (parameter and `_via_github` helper
  dropped; frontend `deriveRole(roles, viaGitHub)` mirrors it). **Flag F1: this makes
  every GitHub-broker user with no realm role read-only — confirm.**
- A token with **no** role claim at all still 401s in `_claim_roles` (unchanged hardening).
- Compat map + old realm roles/groups removed after one release (follow-up, v0.4.0).

---

## 3. Design per step (with resolved decisions)

**Migration numbering** (each reversible, additive-only in this release):

| Rev | Step | Contents |
|---|---|---|
| 012 | 1 | `users.role` data migration: `SUPER_ADMIN→PLATFORM_ADMIN`, `DEVELOPER→DEVELOPER`, `GUEST→NONE`; `downgrade` reverses the mapping (stored strings only). `org_members` does not exist yet — its vocabulary is new from birth in 013 (prompt's "org_members.role etc." adapted). |
| 013 | 3 | `orgs`, `org_members`, `org_settings`, `platform_settings` + seeding from installations (idempotent, `ON CONFLICT`; `downgrade` drops only the new tables). |
| 014 | 6 | `reviews.posting_mode` (default `auto`), `reviews.posted_at`, `reviews.edited_summary`; `review_comments.dismissed/dismissed_by/dismissed_at` (default false/null). `github_review_id` already exists — not re-added. |
| 015 | 7b | `review_comments` enrichment columns (all nullable): `tool`, `rule_id`, `cwe`, `line_start`, `line_end`, `snippet`, `also_detected_by`. |
| 016 | 9 | `review_finding_validations` (+ unique `(comment_id, reviewer_id)`; includes `updated_at` as a small additive extra so a changed verdict shows a truthful "when"). |
| 017 | 11 | `org_invitations`. |

### Step 1 — Roles, backend + Keycloak

- `roles.py`: new constants (`ROLE_PLATFORM_ADMIN` …, `ROLE_NONE`), ladder, compat map
  (isolated in one `_COMPAT_MAP` dict with a "remove in v0.4.0" comment),
  `derive_role` per §2; `require_role` validates against
  `VALID_ROLES = (PLATFORM_ADMIN, ORG_ADMIN, REVIEWER, DEVELOPER, NONE)`;
  shorthands: `require_developer = require_role(PLATFORM_ADMIN, ORG_ADMIN, REVIEWER, DEVELOPER)`,
  `require_super_admin = require_role(PLATFORM_ADMIN)`,
  new `require_reviewer = require_role(PLATFORM_ADMIN, ORG_ADMIN, REVIEWER)`.
  `require_admin` in `dependencies.py` → `PLATFORM_ADMIN`. `users.role` comment +
  `schemas/user.py` docs updated.
- Realm ConfigMap (fresh installs): **add** roles `PLATFORM_ADMIN`, `ORG_ADMIN`,
  `REVIEWER` (keep `DEVELOPER`) and groups `platform-admins`, `org-admins`,
  `reviewers` (keep `developers`); **keep** legacy `SUPER_ADMIN`/`GUEST` roles and
  `super-admins`/`guests` groups for the compat release (N2/§5-Q4: old groups are
  not deleted yet).
- `scripts/keycloak_migrate_roles.sh` (admin REST via `kcadm.sh` in the keycloak pod;
  idempotent; `--dry-run` prints the plan):
  1. create the four groups if missing (map each to its realm role);
  2. move members `SUPER_ADMIN`→`platform-admins`, `DEVELOPER`→`developers`;
  3. **do NOT move `GUEST` members** — print the list of GUEST users, plus (F4) the
     list of users with **no recognized realm role** (they would derive `NONE`), so
     each can be assigned manually;
  4. never delete old groups (removal after the GUEST list is empty = manual follow-up).
- Tests: ladder precedence, compat map (incl. `GUEST` beating `DEVELOPER`),
  unrecognized → `NONE`, guard test per role (`NONE` 403 on a write route),
  `test_route_inventory` still green.

### Step 2 — Roles, frontend

- `deriveRole()` mirrors §2 exactly (compat map, `NONE`, no `viaGitHub` fallback);
  `ANY_ROLE = [DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN, NONE]`,
  `WRITE_ROLES = [DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN]`,
  new `ADMIN_ROLES = [ORG_ADMIN, PLATFORM_ADMIN]` for settings/admin entries.
- Nav entries hidden per effective role (cosmetic — backend stays authoritative).
  Nav is inline per page → introduce a tiny role-aware helper (e.g.
  `navVisibility(role)` or a `*ngIf` on the derived role) used by each header.
- Guard unit tests updated (precedence, `NONE` read routes, `NONE` bounced from writes).

### Step 3 — Org settings, backend

- **Org model (Q1):**
  - `orgs`: `id` UUID PK, `name` (= `github_installations.account_login`),
    `account_type` copied, `installation_id` **nullable UNIQUE FK →
    `github_installations.installation_id` (numeric, unique) ON DELETE SET NULL** —
    nullable so uninstall (row deleted) never wipes the org; `created_at/updated_at`.
    No unique constraint on `name` (a reinstall may issue a new installation id —
    re-link, never duplicate, see below).
  - `org_members`: `id`, `org_id` FK, `user_id` FK, `role` CHECK IN
    `(DEVELOPER, REVIEWER, ORG_ADMIN)`, `created_at`; `UNIQUE (org_id, user_id)`.
    `PLATFORM_ADMIN` is never stored here.
  - **Chain stays joins only**: review → pull_request → repository →
    github_installation → org (via `orgs.installation_id`); **no `org_id` columns on
    reviews or repositories this release**.
- **Seeding (migration 013 + shared helper `app/services/org_provisioning.py`, also
  used by the webhook/link hooks and the dry-run script):**
  - One org per distinct `github_installations` row, upserted by `installation_id`;
    if no org matches, re-link an existing org by `(name, account_type)` (reinstall) —
    else insert.
  - Members = users whose `users.github_installation_id` equals the installation:
    **exactly one linked user → ORG_ADMIN** (the schema's single holder is the linker:
    callback writes it directly; adoption can only match one row per `github_id`);
    **two or more → all DEVELOPER, no auto ORG_ADMIN** ("cannot tell" branch);
    **zero → no members**. Never promote everyone. Existing member rows are never
    downgraded (`ON CONFLICT DO NOTHING` on role).
  - Idempotent (safe re-run), reversible (drops only new tables). Installs with zero
    users stay member-less and are listed by the report.
  - Later user↔installation links (callback + JIT adoption) call the same helper →
    membership row inserted with the same least-privilege rule.
- **`org_settings`** (one row/org; every column nullable = "use platform/config
  default"): `diff_char_cap`, `max_findings_per_agent`, `max_concurrent_reviews`,
  `enabled_agents` (JSON list), `sonarqube_enabled`, `semgrep_enabled`,
  `review_triggers` (JSON list), `min_severity_to_post`, `posting_mode`
  (`auto|staged`), `ai_model`.
- **`platform_settings`** (single row; nullable = fall back to config/code defaults):
  per-field **default** and **ceiling** for the three numerics, plus defaults for the
  non-numeric fields. Initial values:

  | Field | Default | Ceiling (initial) | Hard cap in code (unraisable) |
  |---|---|---|---|
  | `diff_char_cap` | 16000 (`LLM_DIFF_CHAR_CAP`) | 100000 (`DIFF_MAX_CHARS`) | 100000 |
  | `max_findings_per_agent` | 15 | 50 | 100 |
  | `max_concurrent_reviews` | 5 (`BULLMQ_CONCURRENCY`) | 10 | 50 |
  | `enabled_agents` | `["security","complexity","performance","style","test_coverage"]` | — (names validated against `AGENT_DOMAINS`; unknown → 422; empty list allowed = summary-only) |
  | `sonarqube_enabled` / `semgrep_enabled` | `true` / `SEMGREP_ENABLED` | — | — |
  | `review_triggers` | `["pull_request","manual"]` (vocabulary pinned from the webhook's accepted actions + the manual trigger endpoint during Step 4) | — (validated enum) |
  | `min_severity_to_post` | `info` | — (enum `info|low|medium|high|critical`) |
  | `posting_mode` | `auto` | — (enum `auto|staged`) |
  | `ai_model` | `null` (system default) | — (non-empty string) |

- **`resolve_org_settings(org_id) -> EffectiveSettings`** — the *only* merge point:
  `org override → platform default → config/code default`, numerics **clamped to the
  platform ceiling on read** (defense in depth); `org_id=None` → global defaults.
- **API** (paths in existing nested style — see §3 endpoint table):
  - `GET/PUT /orgs/{org_id}/settings` — guard: effective role ≥ `ORG_ADMIN`
    (step order of §2; cross-org → 404). PUT: partial body; **field absent = keep,
    explicit `null` = reset to default**; any numeric above its ceiling → **422**
    (before persistence); enum/agent-name validation → 422. Response: stored
    overrides + effective values + ceilings + per-field `overridden` flags.
  - `GET/PUT /platform/settings` — `PLATFORM_ADMIN` only; validates against the hard
    caps; ceilings themselves cannot exceed the hard caps (422).
  - **Audit = structured log** (no audit table exists): `logger.info` with
    actor id/login, org id, and per-field `{old, new}` — no secrets, no API keys.
- Tests: fallback to defaults, override wins, ceiling rejected 422 **and** clamped on
  read, cross-org GET/PUT → 404, DEVELOPER PUT → 403, platform endpoints non-admin → 403.

### Step 4 — Worker uses org settings

- Job start: resolve org for the review (chain join above) →
  `resolve_org_settings(org_id)`; **structured log of effective settings (no secrets)**.
- Apply: diff cap (replaces direct `settings.LLM_DIFF_CHAR_CAP` read),
  `format_findings(..., limit=...)` (module constant becomes a parameter, default 15),
  `enabled_agents` filters the specialist list in `ReviewOrchestrator` (orchestrator
  summary always runs), scanner flags skip SonarQube/Semgrep calls (existing
  fault-isolation notes cover the skip), trigger gate, min-severity behavior, posting mode.
- **Trigger gate**: job payload gains optional `trigger`
  (`pull_request` from the webhook queue call, `manual` from the API trigger call);
  missing key defaults to `pull_request` (in-flight jobs stay compatible). Disabled
  trigger → job returns `{"skipped": "trigger disabled"}` (review row → `completed`
  with a note, not `failed`).
- **`min_severity_to_post` semantics**: comment severity mapped to scan vocabulary
  (`error→high`, `warning→medium`, `suggestion→low`, `info→info`); **auto mode**:
  if no posted finding meets the threshold → skip the GitHub post entirely (review
  still completes, note recorded, `github_review_id` null); **staged mode**: filters
  the Findings section only — an explicit human "Post" always posts.
  Default `info` ⇒ auto path byte-identical to today.
- **Per-org concurrency**: Redis semaphore `codesage:org:{org_id}:active_reviews`
  (`INCR` check → `DECR` on refusal; TTL 600 s as crash safety; **released in
  `finally`**). Bounded acquire wait (poll ~2 s, default 120 s), then **proceed anyway
  with a structured warning** — availability over strict enforcement (matches the
  codebase's fault-tolerance philosophy); global `BULLMQ_CONCURRENCY` still applies.
  No org resolved → no per-org limit.
- `ai_model` = model-name override applied to the resolved provider
  (precedence: per-user model → org `ai_model` → system default; provider choice
  unchanged).
- Posting: **auto → unchanged** (summary-only, posted at completion, sanitization N/A);
  staged → `status="ready_to_post"`, no GitHub call.
- Tests with a mocked resolver: each effective value changes the right seam; semaphore
  acquire/release (incl. exception path); trigger gate; auto path unchanged.

### Step 5 — Org settings UI

- ORG_ADMIN settings page (org context) + PLATFORM_ADMIN section; numeric fields show
  their ceiling beside them; per-field "reset to default" (PUT with explicit `null`);
  API 422 messages rendered inline per field; read-only for lower roles (route guard
  `ADMIN_ROLES`, backend authoritative).

### Step 6 — Staged posting: data model + worker mode

- Migration 014 (see table). New status `ready_to_post` checked end-to-end:
  `pull_requests.latest_review_status`, `GET /reviews/{id}/status`, review list UI
  (renders the raw string — add a badge/style, no crash), `Review.is_*` properties.
- **Extract `post_review_to_github(review)`** into a shared service module used by the
  worker (auto) and the API (staged). It builds the body per Q3:
  - base = `edited_summary if set else summary`;
  - **staged only**: append a `## Findings` section listing comments with
    `dismissed = false`, grouped by severity (order `error > warning > suggestion >
    info`), then by file — line `path:line`, `[tool]` badge, short message;
  - **auto mode: body = summary exactly as today** (no findings section, no
    sanitization — zero regression; "findings in auto mode" = documented follow-up +
    future org setting);
  - **GitHub 65 536-char body limit**: findings truncated to fit with a closing line
    `… N more findings, see CodeSage`; `PATCH …/summary` caps `summary` at 60 000
    chars; final defensive truncation before send;
  - **sanitization of LLM/scanner-derived content** (findings section always; the
    staged summary too since it originates from the LLM): neutralize `@mentions`
    (zero-width space after `@`), neutralize `#123` issue refs (not `# headings`),
    escape markdown link/image constructs (`[ ] ( ) !` before `[`), strip HTML tags;
    human-edited ordinary markdown (headings, bold, lists) survives. Test with the
    hostile message `@everyone [click](http://evil)`.
- Worker: `posting_mode` from effective org settings (repo-level override skipped —
  no repo settings model exists); `auto` unchanged; `staged` → save review + comments,
  `status="ready_to_post"`, **no GitHub call**, set `posting_mode/posted_at(null)`.
  Auto path sets `posted_at` when it posts (so "posted time" works for both).
- Tests: auto path unchanged (posts at completion, body = summary), staged does not
  call GitHub (`monkeypatch`/mock asserts zero calls), status surfaced correctly.

### Step 7 — Staged posting: API

- Endpoints (existing nested route style):
  - `PATCH /reviews/{review_id}/summary` — body `{summary}` (max 60 000), only while
    `posted_at IS NULL`; sets `edited_summary`; guard: `DEVELOPER+` **and** review's
    org (§2 order) → cross-org **404**.
  - `PATCH /reviews/{review_id}/comments/{comment_id}/dismiss` and `.../restore` —
    sets `dismissed/dismissed_by/dismissed_at`; same guard; 404 if the comment isn't
    in the given review.
  - `POST /reviews/{review_id}/post` — **only for `posting_mode='staged'`** (auto →
    409/400 with clear detail); **race-safe**: `SELECT … FOR UPDATE` on the review
    row, re-check `posted_at IS NULL` and status inside the lock, post to GitHub,
    then conditional `UPDATE … WHERE posted_at IS NULL SET posted_at=now(),
    github_review_id=…`; second concurrent/double click → **409**. GitHub failure →
    `posted_at` stays null, **502** with a retryable detail message (stored, not
    hidden). Stores `github_review_id`.
- **Rule-5 retrofit of existing review-bearing routes (flag F3)**: org membership
  (404) added to `GET /reviews` (list filtered to caller's orgs; PLATFORM_ADMIN sees
  all), `GET /reviews/{id}`, `/status`, `/scan-report`, `retry`, `DELETE`,
  `comments/{id}/resolve`, `GET /pull-requests/{id}`, `/reviews`, and
  `POST /pull-requests/{id}/review`. Without this, "cross-org access denied" cannot
  hold for review data (the panel in 7b reads `GET /reviews/{id}`).
- Tests per endpoint: cross-org 404 (user of org B vs org A's review/comment),
  DEVELOPER-vs-REVIEWER gates, **double post → 409** (two concurrent posts),
  GitHub failure → retryable, non-staged post rejected, summary-after-post rejected.

### Step 7b — Staged posting, UI prerequisite: read-only review panel *(new step,
own commit `feat(web): read-only review panel on PR detail page` — between 7 and 8;
nothing renumbered)*

- **Backend, backward-compatible extension of `GET /reviews/{id}`**:
  - `comments[]` gains nullable `tool`, `rule_id`, `cwe`, `line_start`, `line_end`,
    `snippet`, `also_detected_by` (migration 015) + `dismissed*` fields (from 014) +
    `validations[]` placeholder filled in Step 9;
  - response gains `findings` is **not** added (scan-report endpoint already exposes
    `NormalizedFinding`) — the panel's unit is the AI comment;
  - response gains `viewer_role` (caller's effective role in the review's org) so the
    UI can show/hide controls that depend on org elevation (cosmetic; backend
    authoritative);
  - **enrichment**: worker copies source-finding metadata onto each new comment via a
    deterministic match against the domain's `NormalizedFinding`s (same `file_path`
    and `line_number` inside `[line_start, line_end]`; file-level match only when the
    file has exactly one finding; else left null — panel degrades gracefully).
    Applied to comments created from Step 7b onward; old comments stay null (nullable
    columns = backward compatible).
- **Panel** (read-only): summary (`edited_summary ?? summary`), status; findings
  grouped by file, sorted severity (`error > warning > suggestion > info`) → file →
  line; each row: severity badge, tool badge (+ `also detected by`), message/body,
  file:line range, snippet (rendered as **escaped plain text** — no `innerHTML`, no
  unsanitized markdown anywhere).
- **All states**: none (no review yet → call to action), `pending`/`processing`
  (spinner), `failed` (error message), `ready_to_post` (badge — controls come in
  Step 8), posted (`posted_at` time + link
  `https://github.com/{full_name}/pulls/{number}#pullrequestreview-{github_review_id}`),
  zero-findings ("no findings" empty state). Dismissed findings **muted, not hidden**.
- Component tests per state.

### Step 8 — Staged posting, UI

- On the panel: top banner for `ready_to_post` — **"Post to GitHub"** with a
  confirmation dialog showing *findings that will be posted* and *dismissed count*;
  editable summary textarea (save → `PATCH …/summary`, dirty-state warning, max-length
  enforced client-side too); per-finding dismiss/restore with visual state; after
  posting: controls become read-only, show posted time + GitHub link; API errors
  surfaced visibly. Role gating via `viewer_role` (DEVELOPER+).

### Step 9 — Reviewer validation, backend

- Migration 016: `review_finding_validations (id UUID, comment_id FK, reviewer_id FK
  → users, verdict CHECK (confirmed|false_positive|needs_investigation),
  severity_override NULL CHECK ∈ (info,warning,error,suggestion), note TEXT NULL,
  created_at, updated_at*)` + `UNIQUE (comment_id, reviewer_id)`; upsert
  (`ON CONFLICT … DO UPDATE`) so a changed mind replaces the verdict.
- `PATCH /reviews/{review_id}/comments/{comment_id}/validate` — guard: effective role
  ≥ REVIEWER + org membership (DEVELOPER member → 403; non-member → 404; NONE → 403).
- Review detail response includes each comment's latest validation(s)
  (verdict, `severity_override`, `note`, reviewer login, timestamps).
- Notes stored as-is (plain text); frontend renders escaped (Angular interpolation
  default — asserted by a test that no binding uses `innerHTML`/`bypassSecurityTrust`).
- Tests: DEVELOPER 403, upsert replaces prior verdict, cross-org 404, enum 422,
  NONE 403.

### Step 10 — Reviewer validation, UI

- Under each finding: Confirm / False positive / Override severity / Note — rendered
  only when effective role ≥ REVIEWER (`viewer_role`); existing verdicts (who/what/when)
  visible to everyone in the org; optimistic update with rollback on API error.

### Step 11 — Invitations, backend

- Migration 017: `org_invitations (id, org_id FK, email, role CHECK (DEVELOPER|REVIEWER),
  token_hash (SHA-256 hex of `secrets.token_urlsafe(32)` — raw token only in the link),
  status CHECK (pending|accepted|revoked|expired) default pending,
  expires_at = now() + 7 days, invited_by FK users, created_at)`.
- Endpoints (nested style): `POST/GET /orgs/{org_id}/invitations`,
  `DELETE /orgs/{org_id}/invitations/{invitation_id}`, public
  `GET /invitations/{token}`, `POST /invitations/{token}/accept`.
- **Invitable roles only `DEVELOPER`/`REVIEWER`** (schema enum → 422 otherwise;
  ORG_ADMIN/PLATFORM_ADMIN can never be granted by invitation).
- **Rate limit**: Redis sliding window per org, 20 invites/hour → 429.
- **Mail**: pluggable `MailSender` protocol — `ConsoleMailSender` (dev default; logs
  subject + body incl. the invite link) and `SmtpMailSender` (config: `MAIL_BACKEND`,
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` —
  none exist yet; not required for v0.3.0 since console is the default — N4).
- `GET /invitations/{token}` (public; added to the route-inventory allow-list):
  pending → `{org_name, role, email_masked}` (e.g. `jo***@example.com`); **invalid,
  expired, revoked or already-used → uniform 404** (identical response — no
  enumeration).
- `POST /invitations/{token}/accept` (authenticated): hash lookup; status `pending`
  and not expired else 409 (used) / 410 (expired, revoked); **one transaction**:
  conditional `UPDATE … WHERE status='pending'` (rowcount 0 → 409, single-use +
  double-click safe) then `INSERT INTO org_members … ON CONFLICT (org_id, user_id)
  DO UPDATE SET role = GREATEST-ish CASE (never downgrade — ORG_ADMIN stays
  ORG_ADMIN)`. Email mismatch: **allowed**, `logger.warning` with both emails, and the
  response carries `email_mismatch: true` for the UI warning.
- List + revoke: ORG_ADMIN of that org or PLATFORM_ADMIN (cross-org revoke → 404).
- Tests: expired, reused, revoked, role cap (ORG_ADMIN invite → 422), no-downgrade,
  double accept, cross-org list/revoke → 404, masked uniform GET response, rate limit.

### Step 12 — Invitations, frontend

- ORG_ADMIN: invite form (email + role ∈ DEVELOPER/REVIEWER), pending list, revoke.
- `/invite/accept?token=…`: public load first (404 → friendly "invalid or expired");
  Keycloak `check-sso`: logged in → show org/role + **Accept** button (never
  auto-accept); email mismatch → warning with **Continue anyway** /
  **Sign in with a different account**; not logged in → **Sign in to accept** returning
  to the same URL (reuse the existing `returnUrl` pattern). Token never logged nor
  sent to analytics (no analytics exist — keep it out of `console` and error trackers).

### Step 13 — Release and cluster test

- `export TAG=v0.3.0`; build/push
  `127.0.0.1:5000/codesage/{backend,worker,frontend}:v0.3.0`;
  verify `curl http://127.0.0.1:5000/v2/codesage/<svc>/tags/list`.
- Manifests: exactly those tags, `imagePullPolicy: IfNotPresent`, no `:latest`,
  **never touch postgres/redis/keycloak/PVCs**; new env vars only if truly required
  (settings/ceilings live in DB, mail defaults to console — expect none).
- `kubectl diff` shown **first** (warn loudly on any postgres/redis/keycloak/PVC
  delta) → Alembic via the project's normal mechanism with **migration logs shown
  before rollout completes** → `scripts/org_seed_report.py` dry-run summary (orgs
  that would exist, members per org, orgs without ORG_ADMIN) **shown, wait for OK** →
  `scripts/keycloak_migrate_roles.sh --dry-run` **shown, wait for OK** → real runs
  only after approval → `kubectl -n codesage rollout status` + pods + logs.
- Verification table (check / result / evidence) covering: 4 roles' access,
  cross-org denial, org override changing worker behavior, staged not posted until
  Post, double-post 409, dismissed excluded from body, reviewer validation visible,
  invite flow (new + existing user), re-invite does not downgrade ORG_ADMIN. Repeatable
  parts committed as pytest tests + `scripts/` helpers; ask for any needed token or
  test account.

### Step 14 — Docs

- Role matrix; settings table (defaults + ceilings + hard caps); staged flow
  (mermaid sequence diagram); invitation flow; Keycloak migration script; TAG
  rebuild/deploy runbook; update `AGENTS.md` role/troubleshooting lines to match.

### §3 Endpoint table (final paths — existing nested route style)

| Step | Method + path | Guard (beyond auth) |
|---|---|---|
| 3 | `GET /api/v1/orgs/{org_id}/settings` | member + effective ≥ ORG_ADMIN (else 404/403); PLATFORM_ADMIN ok |
| 3 | `PUT /api/v1/orgs/{org_id}/settings` | same |
| 3 | `GET /api/v1/platform/settings` | PLATFORM_ADMIN |
| 3 | `PUT /api/v1/platform/settings` | PLATFORM_ADMIN |
| 6/7 | *(worker-internal)* `post_review_to_github(review)` | — |
| 7 | `PATCH /api/v1/reviews/{review_id}/summary` | member + ≥ DEVELOPER; unposted only |
| 7 | `PATCH /api/v1/reviews/{review_id}/comments/{comment_id}/dismiss` | member + ≥ DEVELOPER |
| 7 | `PATCH /api/v1/reviews/{review_id}/comments/{comment_id}/restore` | member + ≥ DEVELOPER |
| 7 | `POST /api/v1/reviews/{review_id}/post` | member + ≥ DEVELOPER; staged only; row lock → 409 |
| 9 | `PATCH /api/v1/reviews/{review_id}/comments/{comment_id}/validate` | member + ≥ REVIEWER |
| 11 | `POST /api/v1/orgs/{org_id}/invitations` | member + ≥ ORG_ADMIN; role ∈ {DEVELOPER, REVIEWER}; rate-limited |
| 11 | `GET /api/v1/orgs/{org_id}/invitations` | member + ≥ ORG_ADMIN |
| 11 | `DELETE /api/v1/orgs/{org_id}/invitations/{invitation_id}` | member + ≥ ORG_ADMIN (cross-org 404) |
| 11 | `GET /api/v1/invitations/{token}` | **public** (route-inventory allow-list); uniform 404 |
| 11 | `POST /api/v1/invitations/{token}/accept` | authenticated (any role incl. NONE) |
| retrofit (F3) | `GET /reviews`, `GET /reviews/{id}`, `/status`, `/scan-report`, retry, delete, `comments/{id}/resolve`, `GET /pull-requests/{id}`, `/reviews`, `POST /pull-requests/{id}/review` | member of the review's/org's org → else 404 (PLATFORM_ADMIN bypass) |

---

## 4. Notes resolved by following the prompt or the code

- **N1**: `reviews.github_review_id` exists (migration 006) — Step 6 adds only
  `posting_mode`, `posted_at`, `edited_summary` + `review_comments.dismissed*`.
- **N2**: "Realm JSON" = the ConfigMap — fresh installs only; the live realm is
  changed by `scripts/keycloak_migrate_roles.sh`.
- **N3**: No audit mechanism → structured logs (actor, org, per-field old→new, no secrets).
- **N4**: No mail mechanism → pluggable sender, console/log dev default. SMTP config
  to add later: `MAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT` (587),
  `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS=true` — none present today.
- **N5**: GUEST group members are **not** moved automatically (Q4 change from the
  original prompt); they are listed for manual assignment; old groups deleted only
  after that list is empty.
- **N6**: Pre-existing user↔installation access checks live in `repositories.py`
  (`account_id == github_id`, `_ensure_installation_accessible_to_user`); org checks
  build on top, they don't replace them this release.
- **N7**: Prompt paths replaced by the repo's nested style (§3 endpoint table).
- **N8**: Tests run against local Docker Postgres/Redis only; cluster DBs untouched
  except by Step 13's normal migration mechanism.
- **N9**: Prompt Step 1's "org_members.role data migration" adapted: `org_members`
  is born in 013 with the new vocabulary; 012 migrates `users.role` only.
- **N10**: `review_comments.resolved` (pre-existing) and `dismissed` (new) coexist —
  different meanings; `resolved` untouched.

---

## 5. Resolved decisions (was: open questions)

- **Q1 → Option 1**: first-class `orgs` + `org_members`, seeded from
  `github_installations` (name = account_login, unique `installation_id` FK,
  account_type copied), joins keep the review → repo → installation → org chain, no
  `org_id` on reviews/repos this release. org_members roles restricted to
  DEVELOPER/REVIEWER/ORG_ADMIN; PLATFORM_ADMIN global-only. Least-privilege seeding
  (single linked user → ORG_ADMIN, multiple → all DEVELOPER, none → no members,
  never promote everyone), idempotent + reversible, uninstall/reinstall re-links by
  installation (upsert by id, else by name+type), webhook/link hooks create orgs and
  members for new installations, and a **dry-run summary (orgs, members/org, orgs
  without ORG_ADMIN) is shown before the cluster migration runs**.
- **Q2 → Option 4**: new **Step 7b** (`feat(web): read-only review panel on PR detail
  page`) between 7 and 8, full spec in §3; steps not renumbered.
- **Q3**: staged body = summary (`edited_summary` else `summary`) + Findings section
  (non-dismissed only, severity→file grouping, 65 536-char cap with "N more findings,
  see CodeSage"), single body, **no inline comments**; auto mode byte-identical to
  today (follow-up: optional findings in auto mode + org setting); sanitize all
  LLM/scanner-derived text (@mentions, #refs, markdown links/images, HTML) with the
  hostile-string test.
- **Q4**: internal read-only sentinel `NONE` (no ladder position, not stored, not a
  group); `derive_role` → `NONE` for unrecognized/missing claims, **never default to
  DEVELOPER**; compat map `SUPER_ADMIN→PLATFORM_ADMIN`, `GUEST→NONE` (read-only),
  `DEVELOPER→DEVELOPER`, removed after one release; Keycloak script does **not** move
  GUEST members — prints them for manual assignment, old GUEST group removed only
  after the list is empty; no-org-row → 404 regardless of role (except PLATFORM_ADMIN,
  F2); tests: unrecognized → NONE, legacy GUEST → NONE, NONE → 403 on every write.

---

## 6. Flags — interpretations needing your confirmation (non-blocking)

- **F1 — `via_github` DEVELOPER fallback removed.** Q4's "Never default to DEVELOPER"
  read literally removes the broker fallback (commit `183ffd9` feature): a
  GitHub-brokered user with **no realm role** derives `NONE` (read-only) until an
  admin assigns a group. The realm has no default role/group, so this affects every
  unassigned GitHub user. The migration script will print them (F4). *Say the word and
  I keep the fallback for brokered sessions only (one branch + mirrored frontend test).*
- **F2 — PLATFORM_ADMIN bypasses org membership.** "404 regardless of role for
  no-membership" cannot include PLATFORM_ADMIN, or Step 3's "…or PLATFORM_ADMIN"
  breaks. Implemented as: PLATFORM_ADMIN skips membership but everything else still
  404s cross-org for DEVELOPER/REVIEWER/ORG_ADMIN.
- **F3 — Rule-5 retrofit onto existing review-bearing routes** (list in §3 table) —
  rule 5 says "every new endpoint", but without this a cross-org user still reads
  org A's reviews through today's `GET /reviews/{id}` and the Step 7b panel. Included
  in Step 7 unless you object; existing tests get org fixtures.
- **F4 — script also lists users with NO recognized realm role** (they would derive
  `NONE` under F1), alongside the GUEST list, so nobody is silently locked out.
