# AGENTS.md - CodeSage

## Project Overview

AI-powered code review platform with GitHub integration. Analyzes PRs and provides AI-generated feedback using Google Gemini.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ / FastAPI |
| Database | PostgreSQL 15+ (SQLAlchemy async) |
| Cache/Queue | Redis 7+ |
| AI | Groq (`groq.py`, active review LLM) + Google Gemini (legacy `gemini.py`) |
| Tenancy | Spring Boot 4.0.3 / Java 21 (`repo-tenant-service/` — one enabled repo = one k8s namespace) |
| Frontend | Angular 17+ (standalone components, SCSS) |
| CI/CD | GitHub Actions → AWS EKS (blue-green) |

## Project Structure

```
codesage/
├── backend/                # FastAPI API + background workers
│   ├── app/
│   │   ├── api/routes/     # Endpoint handlers (incl. github_repos.py for GitHub App selection)
│   │   ├── db/models/      # SQLAlchemy models (incl. watched_repos.py)
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── security/       # JWT & auth (jwt.py, dependencies.py)
│   │   ├── services/       # GitHub, GitHub App clients + groq.py (active LLM) / gemini.py (legacy) + review_orchestrator.py
│   │   │   └── agents/     # Multi-agent review system (see "Multi-Agent Review Architecture")
│   │   ├── workers/        # BullMQ review queue (main.py, review_queue.py, review_processor.py)
│   │   ├── chunker.py      # Diff chunking for large PRs
│   │   ├── diff_parser.py  # GitHub diff parsing
│   │   └── main.py         # FastAPI app entry
│   ├── alembic/            # DB migrations (001_initial_schema, 002_add_github_installation_id_to_users, 003_create_watched_repos)
│   ├── Dockerfile / Dockerfile.worker
│   └── tests/              # pytest suite (currently empty)
├── frontend/               # Angular 17 app
│   └── src/app/
│       ├── core/           # api/auth/github services, guards, interceptors, models (user, repository, pull-request)
│       ├── features/       # Feature modules (landing, auth, dashboard, pull-requests, repositories, settings)
│       └── shared/         # Reusable components
├── repo-tenant-service/    # Spring Boot 4 service: repo enable -> k8s namespace/tenant (README inside)
├── docker-compose.yml      # Local dev (PostgreSQL, Redis, PgAdmin, monitoring)
└── .github/workflows/      # CI/CD pipeline (ci-cd.yaml)
```

**Note**: `infrastructure/k8s/` (full k3s manifest tree + build-and-deploy script) and `infrastructure/webhook-proxy/` (path-filter proxy + ngrok tunnel, systemd units) now exist; `infrastructure/postgres/init.sql` and monitoring configs referenced by docker-compose/CI still do not.

## Developer Commands

### Backend

```bash
cd backend

# Setup
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/Mac
pip install -r requirements.txt

# Env setup
cp .env.example .env           # Edit with credentials

# Database
alembic upgrade head           # Apply migrations
alembic revision -m "msg"      # Create new migration

# Run API server
uvicorn app.main:app --reload  # Dev server on :8000

# Run worker (separate terminal)
python -m app.workers.main

# Tests
pytest tests/ -v               # Run all tests
pytest tests/ -v -x            # Stop on first failure
pytest tests/ --cov=codesage   # With coverage

# Lint / Format / Type-check
ruff check .
black --check .
mypy .
bandit -r .                    # Security scan
```

### Frontend

```bash
cd frontend

npm install                    # Install deps
npm start                      # Dev server on :4200
npm run build                  # Production build
npm run test                   # Karma/Jasmine tests (watch mode)
npm run test:ci                # Headless CI tests (ChromeHeadlessCI: Chrome, Edge fallback)
npm run lint                   # ESLint
npm run lint:fix               # ESLint auto-fix
npm run type-check             # tsc --noEmit (app + spec tsconfigs)
npm run format                 # Prettier write
npm run format:check           # Prettier check (CI gate)
```

### repo-tenant-service (no Java on host — run Maven in Docker)

```bash
# Tests (28)
docker run --rm -v "$PWD":/workspace -v faas-m2:/root/.m2 \
  -w /workspace/repo-tenant-service maven:3.9.6-eclipse-temurin-21 mvn test -B

# Image (multi-stage — builds the jar inside, no mvn package on host)
docker build -t codesage-repo-tenant-service:latest \
  -f repo-tenant-service/Dockerfile ./repo-tenant-service
```

### Docker (infrastructure only)

```bash
docker-compose up -d           # PostgreSQL + Redis
docker-compose ps              # Verify services
docker-compose down            # Stop services
```

### Docker Compose profiles

| Profile | Services |
|---------|----------|
| `database` | PostgreSQL, Redis |
| `backend` | API server |
| `worker` | Background worker |
| `frontend` | Angular dev |
| `debug` | PgAdmin, Redis Commander |
| `monitoring` | Prometheus, Grafana, Jaeger |
| `full` | Everything |

```bash
docker-compose --profile full up -d
docker-compose --profile database up -d
```

## Architecture Notes

- **API prefix**: `/api/v1` (configured via `API_V1_PREFIX` in `.env`)
- **Auth flow**: GitHub OAuth → JWT (access + refresh tokens). Tokens stored encrypted in `oauth_tokens` table.
- **Review queue**: BullMQ on Redis (queue name from `BULLMQ_REVIEW_QUEUE`, default `review-requests`). Reviews are queued as background jobs, processed by `app.workers.main` with `BULLMQ_CONCURRENCY` workers.
- **GitHub App**: Used for repository access and webhook events (separate from OAuth App). Installations are stored via `users.github_installation_id` (numeric GitHub installation ID) — added in migration 002.
- **GitHub App repo selection**: `GET /api/v1/github/status` (installation state), `GET /api/v1/github/repos` (installation repos + enabled flags from `watched_repos`), `POST /api/v1/github/repos/selection` (persist enabled repos). Router mounted at `/github` prefix in `app/api/__init__.py`.
- **GitHub App install flow**: the Install button must call `GET /api/v1/auth/github/app/install-url` and use the returned `{url}` as-is — its `state` is a JWT signed with `STATE_TOKEN_SECRET` (HS256, `sub`=user id, exp 600 s). GitHub redirects to the App **Setup URL** → `GET /api/v1/auth/github/app/callback?installation_id&setup_action&state` → writes `users.github_installation_id` → redirects to `{FRONTEND_URL}/github/callback?success=…` where `GithubCallbackComponent` re-checks `GET /github/status`. **Do not** use `GET /repositories/install-url` for this flow — it issues an unsigned random state and the callback will reject it (returns `?success=false`). The GitHub App *Setup URL* (external GitHub setting) must point at the callback endpoint.
- **Watched repos**: `watched_repos` table (migration 003) stores which GitHub repos a user enabled for review processing — unique constraint on `(user_id, repo_id)`.
- **Repo → tenant (namespace)**: `POST /github/repos/selection` and the `installation_repositories/removed` webhook diff `watched_repos` transitions and fire **best-effort** calls (`app/services/repo_tenant.py`, 3 s timeout, failures logged+swallowed — a save never 5xx's because the service is down) to the `repo-tenant-service` (`POST /api/v1/repos/internal/enable|disable`, `X-Service-Token` = `REPO_TENANT_INTERNAL_TOKEN`). One repo = one namespace; **disable deletes the namespace first, then the `repo_tenants` row** (row kept if the K8s delete fails — no orphaned namespaces). Quota defaults are injected from ConfigMap `repo-tenant-config` (`DEFAULT_*`) and `QUOTA_SERVICE_URL` is empty by default, so enabling never blocks on another microservice. Schema: `repo_tenants` via Alembic 009 (service runs `ddl-auto: none`). Ingress: `/api/v1/repos` → `repo-tenant-service:8085` (declared before the generic `/api` rule); JWT read API `/repos`, `/repos/{id}`, `/repos/{id}/status`; internal list `GET /internal/namespaces`.
- **Webhook endpoint**: `POST /api/v1/webhooks/github` — verifies signatures using `GITHUB_WEBHOOK_SECRET`.
- **CORS**: Comma-separated origins in `.env`. Default includes `http://localhost:4200` (Angular dev).
- **Frontend entry**: `frontend/src/main.ts` → `app.component.ts` → `app.routes.ts`
- **Backend entry**: `backend/app/main.py` (FastAPI app)
- **Worker entry**: `backend/app/workers/main.py`

## Multi-Agent Review Architecture

AI reviews run through a multi-agent pipeline (current focus of the `multi-agent` branch):

- **`app/services/review_orchestrator.py`** — `ReviewOrchestrator`: runs 5 specialist agents **in parallel** (`asyncio.gather` with `return_exceptions=True`), tolerates individual agent failures, then synthesizes a final review via `OrchestratorAgent`.
- **`app/services/agents/base_agent.py`** — `BaseAgent`: abstract base handling LLM invocation + tolerant JSON extraction (regex `{...}` match) from LLM output.
- **Specialist agents** (`agents/specialist_agents.py`): `SecurityAgent`, `ComplexityAgent`, `PerformanceAgent`, `StyleAgent`, `TestCoverageAgent` — each with its own temperature (`AGENT_*_TEMPERATURE` in config).
- **`agents/orchestrator_agent.py`** — `OrchestratorAgent.synthesize()`: deterministic Python merge of agent results (dedupe by file+line, strongest severity, exact statistics) + a summary-only LLM call (compact headlines) — sized for Groq's ~8000 TPM/request free tier.
- **Schemas** (`agents/schemas.py`): `ReviewContext`, `AgentResult`, `AgentComment`, `ReviewResult`, `ReviewStatistics`.
- Per-agent token usage is tracked via `GroqClient.total_usage()` and attached to the final review.

## CI/CD Pipeline

Order: `code-quality` → `security-scan` → `test` → `build` → `deploy-dev` → `deploy-staging` → `deploy-production`

- **Branches**: `develop` → dev env, `main` → staging → production
- **Deploy**: AWS EKS with blue-green for production
- **Images**: `ghcr.io/<repo>/{frontend,api,worker}`
- **Python version in CI**: 3.12 (local uses 3.11+)
- **Node version**: 20

## Important Conventions

- **Backend linters**: `ruff` (lint), `black` (format), `mypy` (types), `bandit` (security)
- **Frontend linters**: ESLint + Prettier + TypeScript strict checks
- **Frontend CI scripts** (all present in `package.json`): `type-check`, `format:check`, `test:ci` (Karma launcher `ChromeHeadlessCI` — Chrome first, falls back to Edge `msedge.exe` on Windows), `lint`/`lint:fix`, `format`. Template a11y lint errors are fixed in templates, never suppressed.
- **Tests directory** (`backend/tests/`) currently empty — pytest is configured but no tests exist yet.
- **Async database**: Uses `asyncpg` driver (`postgresql+asyncpg://`). Do not use sync SQLAlchemy patterns.
- **Redis has password** in docker-compose: `redis_password`. Local `.env` must match if connecting to Docker Redis.
- **Monaco editor** is bundled via `ngx-monaco-editor-v2` for diff viewing.

## GitHub OAuth Redirect Error

If you see "redirect_uri is not associated with this application":

1. Verify `GITHUB_CALLBACK_URL` in `.env` matches exactly what's configured in the GitHub OAuth App settings
2. Local callback should be: `http://localhost:8000/api/v1/auth/github/callback`
3. Check the GitHub OAuth App at: GitHub Settings → Developer settings → OAuth Apps → CodeSage
4. The callback URL in GitHub must match the `GITHUB_CALLBACK_URL` env var character-for-character (including trailing slashes)

## Environment Files

| File | Purpose |
|------|---------|
| `.env.example` (root) | Minimal env for tooling |
| `backend/.env.example` | Full backend config template |
| `backend/.env` | Active backend config (gitignored) |
| `.env.docker` | Docker-specific overrides (gitignored) |

## Database

- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic (config in `backend/alembic.ini`)
- **Default Docker DB**: `postgresql://codesage:codesage@localhost:5432/codesage`
- **Test DB**: `postgresql://test:test@localhost:5432/codesage_test`
- **Migrations on disk**:
  1. `001_initial_schema.py` — users, oauth_tokens, github_installations, repositories, pull_requests, reviews, review_comments, webhook_events
  2. `002_add_github_installation_id_to_users.py` — `users.github_installation_id` (numeric GitHub App installation ID)
  3. `003_create_watched_repos.py` — `watched_repos` table (user repo-selection for reviews)
  4. `004_add_updated_at_to_webhook_events.py` / `005_add_updated_at_to_review_comments.py` — `updated_at` + triggers (schema-drift fix)
  5. `006_add_review_result_columns.py` — `reviews.overall_severity`, `reviews.github_review_id`, `review_comments.suggestion`
  6. `007_add_llm_settings_to_users.py` — per-user LLM settings
  7. `008_keycloak_identity_and_role.py` — `users.keycloak_id`, `users.role`
  8. `009_create_repo_tenants.py` — `repo_tenants` (repo_id BIGINT UNIQUE, namespace_name VARCHAR(63) UNIQUE, owner_user_id FK → users ON DELETE SET NULL) — schema for `repo-tenant-service` (JPA `ddl-auto: none`)

## Key Environment Variables

All settings live in `backend/app/config.py` (pydantic-settings, loaded from `backend/.env`). Required (no default): `SECRET_KEY` (min 32 chars), `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (PEM), `GITHUB_WEBHOOK_SECRET`, `STATE_TOKEN_SECRET`, `GEMINI_API_KEY` (legacy client), `GROQ_API_KEY` (active review LLM).

Notables with defaults:
- `GITHUB_APP_SLUG` — used to build the GitHub App installation URL
- `GROQ_MODEL` (default `openai/gpt-oss-120b` — active review LLM via `app/services/groq.py`), `LLM_DIFF_CHAR_CAP` (16000 — LLM prompt diff cap, Groq free tier ≈ 8000 TPM/request), legacy `GEMINI_MODEL`/`GEMINI_MAX_TOKENS`/`GEMINI_TEMPERATURE`, `AGENT_*_TEMPERATURE` (per-specialist-agent temps)
- `BULLMQ_REVIEW_QUEUE` (`review-requests`), `BULLMQ_CONCURRENCY` (5)
- `REDIS_URL` — **default is `redis://redis:6379/0` (Docker service name)**; for local non-Docker dev with the Docker Redis, use `redis://:redis_password@localhost:6379/0`
- `DATABASE_URL` — **default is `postgresql+asyncpg://codesage:codesage@postgres:5432/codesage` (Docker service name)**; use `localhost:5432` outside Docker
- `API_V1_PREFIX` (`/api/v1`), `FRONTEND_URL`, `CORS_ORIGINS`

## Session Progress Log

### Completed Fixes & Features

#### OAuth & Authentication
- Fixed GitHub OAuth flow: backend now handles redirect and returns JWT to frontend via URL params
- Added `POST /auth/github/callback` endpoint for token exchange
- Added `prompt=select_account` to GitHub OAuth authorization URL
- Fixed `User.is_active` property that was causing authentication failures
- Updated auth interceptor to allow `/auth/me` without token (prevents "No credentials provided" error)

#### Database & Models
- Fixed `User-PullRequest` broken relationship (removed invalid relationship causing session crashes)
- Fixed UUID-to-string conversion in `UserResponse` and `RepositoryResponse` Pydantic schemas
- Changed `lazy="selectin"` to `lazy="select"` on relationships to prevent async session errors
- Fixed `Review` join in `get_repository_detail` to go through `PullRequest` model

#### Repository Management
- Added `GET /repositories/github` endpoint to fetch user's GitHub repositories
- Added `POST /repositories/connect` endpoint to connect a GitHub repository
- `GitHubInstallation` uses `current_user.github_id` as `installation_id` (with race condition handling)
- Removed fake installation logic — connect now requires real GitHub App installation
- Added `GET /repositories/install-url` for GitHub App installation flow
- Added `POST /repositories/installations/sync` to sync installation data from GitHub
- Repository listing now uses GitHub App installation tokens (not OAuth `/user/repos`)
- Added `get_user_app_installations()` and `get_app_installation_url()` to GitHubService

#### GitHub App Installation Flow (OAuth + App)
- OAuth is now identity-only (login); repository access comes from GitHub App installation
- Added `GET /repositories/install-url` — returns GitHub App installation URL with state
- Added `POST /repositories/installations/sync` — upserts installation and repos after redirect
- Fixed webhook PR handler to use real `install_record.id` (UUID FK) instead of numeric GitHub ID
- Fixed `review_processor` to pass `repo.installation.installation_id` (numeric) to GitHub API
- `get_installed_repos()` now uses installation token via `/installation/repositories`
- Removed per-repository webhook creation (`create_repository_webhook` raises RuntimeError)
- Added `GITHUB_APP_SLUG` config for installation URL generation
- Frontend repository list now shows "Install GitHub App" button

#### Frontend API Integration
- Mapped backend snake_case to frontend camelCase in `github.service.ts`
- Fixed `repos.filter is not a function` by mapping paginated response correctly
- Added "Switch Account" and "Connect Repository" UI features

#### Repo Selection via GitHub App (multi-agent branch)
- Added `users.github_installation_id` column (migration 002) — links user to a real GitHub App installation
- Added `watched_repos` table (migration 003) + `WatchedRepo` model — per-user enabled repo list (unique on `user_id` + `repo_id`)
- Added `app/api/routes/github_repos.py`: `GET /github/status`, `GET /github/repos` (merges installation repos with enabled flags), `POST /github/repos/selection` (upsert selection)
- Added `app/services/github_app.py` with `get_installation_repos()` using installation tokens
- Frontend repository list consumes the new endpoints via `github.service.ts`

#### Multi-Agent Review System (multi-agent branch)
- Added `app/services/agents/` package: `BaseAgent`, `OrchestratorAgent`, specialist agents (Security, Complexity, Performance, Style, TestCoverage), shared schemas
- Added `app/services/review_orchestrator.py` — parallel specialist execution with fault tolerance, then synthesis
- Per-agent temperature settings added to config (`AGENT_SECURITY_TEMPERATURE`, etc.)

#### Frontend Tooling & CI Scripts (local setup)
- Added ESLint + Prettier + Karma configs (`frontend/.eslintrc.json`, `.prettierrc`, `.prettierignore`, `karma.conf.js`, `tsconfig.spec.json`)
- Added CI-referenced `package.json` scripts: `test:ci`, `type-check`, `format`, `format:check`, `lint:fix`; added `test`/`lint` architect targets
- `test:ci` uses custom Karma launcher `ChromeHeadlessCI` (Chrome headless, Windows fallback to Edge `msedge.exe`)
- Fixed 11 template a11y lint errors in component templates instead of suppressing rules
- Added `bullmq>=3.0.0` to `backend/requirements.txt` (worker imported it undeclared → crash on import)
- All gates verified exit 0: `format:check`, `lint` (0 errors), `type-check`, `test:ci` (4/4), `build`

#### GitHub App Installation Fix — `github_installation_id` not persisted (multi-agent branch)
- **Root cause**: Install button called `GET /repositories/install-url`, which issues an **unsigned random** `state` (`secrets.token_urlsafe(32)`), while `/auth/github/app/callback` verifies a JWT signed with `STATE_TOKEN_SECRET` → `jwt.decode` raised → `?success=false` → column never written
- `github.service.ts`: added `getInstallUrl()` → `GET /auth/github/app/install-url` (signed state); `installGitHubApp()` uses the returned `url` as-is (never builds the GitHub URL manually); removed buggy `getGitHubAppInstallUrl()`
- Fixed auth interceptor: `publicAuthUrls` contained `'/auth/github'`, whose `includes()`-match also stripped the auth header from protected `/auth/github/app/install-url` → 401 + forced logout on Install click
- `auth.py` callback: `state` now `str | None = Query(None)` with explicit guard — missing/invalid state redirects `?success=false` instead of FastAPI 422
- Added `github/callback` Angular route + `GithubCallbackComponent` (previously swallowed by `**` wildcard → landing page): calls `getInstallStatus()`, updates shared state, navigates to `/dashboard`
- Shared install state: `GithubService.githubInstalled` signal (updated inside `getInstallStatus()` via `tap`); Install button is `@if (!githubInstalled())`; repository-list and dashboard re-read status on init so reloads never show a stale "not installed" value
- Connect modal switched to `GET /github/repos` + `POST /github/repos/selection` — legacy `/repositories/github` needs `github_installations` rows that this flow never creates (409)
- API-level verification: missing state → `success=false`, invalid state → `success=false`, valid signed state → `success=true` + DB write; `/github/status` → `installed: true`; user row reset to NULL as smoke-test baseline
- **External prerequisite**: GitHub App *Setup URL* must be `http://localhost:8000/api/v1/auth/github/app/callback`

#### Frontend Redesign (Industrial Terminal Aesthetic)
- Complete visual overhaul using dark theme with JetBrains Mono and electric green (#00e87b) accents
- Redesigned global styles (`styles.scss`, `_reset.scss`, `_mixins.scss`)
- Redesigned all pages: landing, login, callback, dashboard, repository list, PR list, PR detail, settings
- Dark backgrounds (#0a0a0a, #111111), subtle borders (#1e1e1e), monospace typography throughout

#### Repository Selection Workflow — 5-Phase Fix (multi-agent branch, uncommitted)
Single review switch = `watched_repos`; all verified with an automated 18/18 API + HMAC-webhook suite:

- **Phase 1 — modal becomes a real toggle with full-state sync**: `RepoSelectionPayload.sync` flag; when `sync=true` the backend disables watched rows **missing** from the payload (reconcile-by-disable, survives stale payloads). `saveRepoSelection()` now posts `{ repos, sync: true }`. Connect-modal rows toggle both ways (`Selected ✓` ⇄ `Select`), every toggle saves the full list; added modal load-error + Retry, inline `save-error` (`role="alert"`), SCSS for `.modal-error`/`.save-error`.
- **Phase 2 — `watched_repos` is THE switch**: added `POST /repositories/{id}/enable|disable` (frontend already called them — they silently 404'd before); `/enable|/disable`, `PATCH`, `/connect` sync `watched_repos`; `DELETE` drops the watched row (removal now sticks); `GET /repositories`, `GET /{id}`, `GET /{id}/detail` derive `enabled` from the watched map (absent row ⇒ false, so badges tell the truth even when the legacy `repositories.enabled` flag diverges); webhook handler **dropped the `if repo.enabled:` gate** (Case C verified: legacy=off + watched=on still reviews).
- **Phase 3 — pending-selection summary**: repository list shows "N repositories selected for review — they'll appear here after their first PR event" + Manage link (`selectedPending` getter dedups grid `fullName` vs App `name`; `appSelected` refreshed on init and after modal toggles). Grid-merge of virtual cards left as backlog.
- **Phase 4 — webhook robustness**: owner resolution now selects **all** users matching `github_installation_id` (first watching wins); distinct ignore reasons (`no user linked to this installation` vs `repository not selected by installation owner`); `installation.deleted` NULLs users' `github_installation_id`; `installation_repositories/removed` disables matching watched rows; `GET /github/repos` maps httpx errors →409 (stale install) /502 (GitHub unreachable).
- **Phase 5.3** (server-side payload validation) intentionally skipped as optional.

#### Pre-existing Bugs Fixed to Make Verification Pass (backend)
- **Schema drift: `updated_at` missing from `webhook_events` and `review_comments`** — `Base` declares it for every model, `001` omitted those two tables ⇒ *every* webhook event INSERT and any `Repository`/`PullRequest` delete (relationship load) crashed `UndefinedColumnError`. Fixed by migrations **`004`** + **`005`** (column + `update_*_updated_at` trigger). Full mapped-vs-DB audit now shows zero diffs.
- **Worker never started on Windows**: `loop.add_signal_handler` → `NotImplementedError` (guarded with try/except), bullmq connection opts passed `{"url": ...}` dict → `Redis.__init__() got unexpected kwarg 'url'` (bullmq needs a **URL string**: fixed in `workers/main.py` + both call sites in `review_queue.py`), `@worker.on("event")` decorator → bullmq 3.x `on(event, function)` takes two args (converted to `worker.on(...)` calls), `worker.isRunning()` doesn't exist and the worker was never actually run (replaced polling loop with `await worker.run()`), `process_job(job)` signature → bullmq calls `processor(job, token)` with a `Job` **instance** (signature `(job, token=None, *args)` + `job.id` instead of `job.get('id')`).
- **Local dev B0 status**: `users.github_installation_id = 163874087` (live installation — a newer one than `163858576` from the earlier session; written by the real callback flow). `github_installations` has a row (created via simulated `installation/created` webhook). Setup URL external prerequisite still applies for future re-installs.
- **Verification suite** (temp scripts `verify_selection.py` / `audit_schema.py`): V0 status/listing, V1 selection round-trip (sync upsert/reconcile/legacy semantics), F install-created, D not-watched reason, A watched → `created_review` + worker pickup (`pending → processing`), C legacy-off single-switch + truthful badge, V3 enable/disable sync, V4 delete-sticks + later event gated, E repositories-removed → switch off, FINAL selection restored — **18/18 PASS**. All 5 frontend gates green (`format:check`, `lint`, `type-check`, `test:ci` 4/4, `build`); backend files compile; services running (uvicorn :8000, worker on `review-requests`, ng serve :4200).

#### PR Code Review Workflow — Full Verification & Brief Implementation (this session)

- **Migration 006** (`006_add_review_result_columns.py`, rev 005→006): `reviews.overall_severity`, `reviews.github_review_id` (indexed), `review_comments.suggestion` — applied (`alembic current` = `006 (head)`).
- **Webhook response contract** (per brief): invalid signature → **401** (warn-logged with event + delivery); unknown event → `{"status":"skipped"}`; non-accepted action (incl. `closed` after its PR-state update) → `{"status":"skipped"}`; unwatched → `{"status":"ignored","reason":"repo not enabled"}` (no-linked-user vs not-selected detail now goes to logs only); queued → `{"status":"queued","review_id":"<uuid>"}`; duplicate `delivery_id` (IntegrityError) → skipped.
- **Duplicate review guard (final semantics)**: skip only when a prior *processed* `WebhookEvent` exists for same repo + action + `pull_request.id` + head-sha (different delivery) **AND a Review row already exists for that PR** — the review-exists clause comes straight from the brief and prevents gate-miss events (ignored but `processed=true`, never queued) from blocking later accepted deliveries.
- **Worker** (`review_processor.py`, rewritten): idempotency guard returns success + `skipped` unless status == pending (no BullMQ retry, no re-raise — DB row is source of truth); installation token from `get_installation_token()` only; `get_pull_request_files` paginates (`github.py`, per_page=100 loop); binary/no-patch files filtered; diff cap 100 000 chars + `[diff truncated — showing first 100k characters]`; empty-after-filter → completed with `"No reviewable changes found."` (no LLM call); language = extension frequency with `"unknown"` fallback; pipeline LLM → post → store → completed; `post_pr_review()` posts a single summary with `event="COMMENT"`, `commit_id` = stored `head_sha`, no inline comments; post 401/403/404/422 handled (404 → completed + note in `error_message`, 422 → failed with full body logged); full tracebacks logged, never re-raised. `_classify_error` is URL-aware (Gemini HTTP errors no longer mislabeled as GitHub). Job shape `{review_id}` unchanged.
- **LLM layer** (HTTP call structure in `gemini.py` untouched): added `ReviewParseError` (carries raw response), markdown-fence stripping, safe defaults for summary/severity/comments/statistics, and GitHub-Markdown summary instructions in both `_build_review_prompt` and `orchestrator_agent.py` synthesis (the orchestrator's `summary` is what gets posted).
- **GEMINI_MODEL retired**: Google returns `404 NOT_FOUND … models/gemini-2.0-flash is no longer available` (API key itself valid — `/v1beta/models` lists 50 models). Switched `backend/.env` + `config.py` default to **`gemini-2.5-flash`** (verified 200 OK). Config values only.
- **Redis repair**: :6379 was dead (queue_review hung / BullMQ never got jobs). `C:\Redis\redis-server.exe` is Redis **3.2.100** — cannot read the repo's `dump.rdb` (RDB v9) *and* cannot execute BullMQ's Lua scripts (`Unknown Redis command called from Lua script`) → unusable for this stack. The working binary is **`C:\Users\Waelbhz\AppData\Local\Programs\redis\redis-server.exe` (5.0.14.1)**, started with cwd = repo root (loads `dump.rdb`; conf: port 6379, `dir ./`, no password; logs to untracked `server_log.txt` at repo root). BullMQ/Redis infra untouched.
- **Services**: single uvicorn :8000 + single worker on `review-requests` + Redis 5.0.14.1. Note: `Start-Process -PassThru` returns a wrapper PID, not the real process — match/kill service processes **by command line**, never by the returned PID (this caused duplicate uvicorn/worker accumulation).
- **Verification results**: selection suite **18/18** (expectations migrated to the new response contract); brief smoke **25/25** — 401 / skipped event / skipped action / ignored-unwatched / `opened`→queued + duplicate→skipped / pending→processing→completed (32 s) / `github_review_id` + Markdown summary + severity stored / GitHub review posted by `codesage-ai-bot[bot]` with `state=COMMENTED`, body byte-identical to stored summary, id match / selection restored; frontend gates all green (`format:check`, `lint` 0 errors, `type-check`, `test:ci` 4/4, `build`).
- **Smoke fixture constraint**: GitHub App has `pull_requests: write` (PR creation + review posting OK) but only `contents: read` → branch/commit creation 403; testWAEL has a single branch. Fixture = existing open **PR #1 on `Wael-BenHariz/tp3` (branch `test-codesage`, 1 commit ahead)**; tp3 enabled for the run, then selection restored to testWAEL-only. `ReviewComment` rows are written only when the LLM returns `comments[]` (20-issue run → 20 rows; no-issue run → severity `info`, 0 rows) — by design. GitHub stores posted comment-reviews as `state=COMMENTED`, `event=null` (the POST-side enum is `COMMENT`).

#### Workstream A — SonarQube Static Analysis → 5-Agent LLM Refinement (this session)

- LLM-as-analyzer replaced: new `app/services/sonarqube.py` runs **sonar-scanner via `asyncio.create_subprocess_exec` only** against a **unique per-review SonarQube project key**, polls `ce/activity`, fetches paginated issues, groups them per specialist (`group_issues_by_agent`), and **always deletes the project** (best-effort `finally`).
- `ReviewContext` gained `sonar_issues` + `with_issues()` slicing and `sonar_scan_failed`; **diff still passed as before**. `ReviewResult` shape, `groq.py`, `base_agent.py`, and the BullMQ job shape are unchanged.
- `specialist_agents.py` rewritten as SonarQube-refinement prompts via a shared `_SonarSpecialistAgent` base (per-agent DOMAIN + `AGENT_*_TEMPERATURE`); `review_orchestrator.run(context, sonar_groups)` slices issues per domain (semaphore kept); `OrchestratorAgent` synthesis reports the SonarQube source and a "Static analysis unavailable" note on fallback.
- **Hard constraint**: SonarQube failure never fails a review — `scan()` wraps `httpx.HTTPError`/`OSError` into `SonarQubeError`; the worker catches it (incl. bare `Exception`) and falls back to empty groups with a completed review.
- `github_app.fetch_file_content()` fetches full PR file contents with the **installation token** as scanner input.
- Config: `SONARQUBE_URL`/`SONARQUBE_TOKEN` in `config.py`; migration **006** adds `reviews.overall_severity`, `reviews.github_review_id`, `review_comments.suggestion`.
- Verified on host: system UP, project lifecycle + cleanup, real Java/Python scans → correct agent groups, all 10 grouping/priority cases, F1–F5 fallback tests, 21/21 pipeline smoke, queue→worker GitHub-boundary test.

#### Workstream B — Kubernetes (k3s) + Multi-Stage Alpine Images (this session)

- `infrastructure/k8s/`: namespace, MetalLB (pool `10.171.24.200-210`), ingress-nginx LoadBalancer → **`10.171.24.201`**, postgres, redis (password `redis_password`), backend/worker/frontend Deployments+Services, Secret `codesage-backend-secret`, base+overlay kustomizations, `APPLY_ORDER.md`, `scripts/build-and-deploy.sh` (Docker build → `k3s ctr images import` → rollout; worker image is **not** retagged over the backend image).
- Images: `backend/Dockerfile` + `backend/Dockerfile.worker` — python:3.11-alpine multi-stage, `sonar-scanner` 5.0.1 + OpenJDK 17 on PATH in the final stage (bundled **glibc** JRE removed + `use_embedded_jre=false` because musl can't exec it; `ENV SONAR_SCANNER_VERSION` must be redeclared in the final stage — stage ENVs don't cross `COPY --from`); `frontend/Dockerfile` (node:20-alpine build → nginx, copies `dist/codesage-frontend/browser`, `/api` proxy in `frontend/nginx.conf`); `.dockerignore` files added for both.
- Deployed & verified end-to-end: all pods Running; health via pod and via `http://10.171.24.201/api/v1/health`; SPA + deep-route fallback 200; **in-cluster SonarQube DNS** (`sonarqube-sonarqube.sonarqube.svc.cluster.local:9000`) UP from pods; `sonar-scanner --version` inside pods; in-cluster scan → 6 issues correctly grouped + project cleanup; DB from pod (alembic 006); BullMQ job queued from host → **pod worker** processed it → classified GitHub 401 boundary; frontend gates all green (`format:check`, `lint` 0 errors, `type-check`, `test:ci` 4/4 with `CHROME_BIN=/usr/bin/chromium`, `build`).
- Frontend page served by the pod's nginx (production build), not `ng serve`.

#### Full Live E2E — real GitHub + Groq + SonarQube through k3s (this session)

- Real credentials wired into `backend/.env` + k8s Secret (GitHub OAuth id/secret, real App RSA key for App 3755554, `CODESAGEsecret` webhook secret, Groq/Gemini keys) and validated **from inside the backend pod**: App JWT → 200 with 2 installations, Groq `openai/gpt-oss-120b` completion → 200, Gemini → 200.
- User configured the GitHub side: OAuth App callback, GitHub App authorization callback + Setup URL + Webhook URL/secret all pointing at `10.171.24.201` endpoints.
- **14/14 checks**: bad HMAC → 401; signed `pull_request opened` webhook (built from the **real** PR object) → `http://10.171.24.201/api/v1/webhooks/github` → queued → pod worker → real installation token → real PR files (`Wael-BenHariz/tp3` PR #1, `cbd2c5d8`, +214) → in-cluster SonarQube scan (**19 issues**, project deleted, 204) → 5 Groq agents + synthesis (all 200) → review **posted on GitHub**: [`#pullrequestreview-5317652210`](https://github.com/Wael-BenHariz/tp3/pull/1#pullrequestreview-5317652210), author `codesage-ai-bot[bot]`, state `COMMENTED`, body byte-identical to stored summary; DB row `completed | error | 5317652210 | summary 2117 chars | 19 comments`.
- Fresh k3s DB left with a realistic onboarding seed: user (`github_id=75458407`, `github_installation_id=164169573`) + `github_installations` row + watched tp3 (`repo_id=320397876`).

#### Public Webhook Exposure — ngrok Tunnel + Path-Filter Proxy (2026-09-26)

- **Live GitHub App webhook URL**: `https://jerica-holmic-nahla.ngrok-free.dev/api/v1/webhooks/github` (secret `CODESAGEsecret`). ngrok free tier; the domain is ngrok-assigned (reserving one fails on the free plan — `ERR_NGROK_206`) but verified stable across tunnel restarts.
- Chain: github.com → ngrok agent → `127.0.0.1:8081` path-filter proxy (`infrastructure/webhook-proxy/proxy.py` — forwards **only** `POST /api/v1/webhooks/*`, everything else 404) → `http://10.171.24.201` ingress → backend pod.
- Both hops are systemd units enabled at boot: `code-sage-webhook-proxy.service` + `code-sage-webhook-tunnel.service`. The committed config template `infrastructure/webhook-proxy/ngrok.yml` ships `REPLACE_ME` placeholders; the live config with the real authtoken is `~/.config/ngrok/ngrok.yml`, outside the repo.
- Verified through the public URL: unknown path → 404, bad HMAC → 401, valid signed ping → 200 (full GitHub→ngrok→proxy→.201→backend chain).
- Ingress is **hostless** (K8s rejects an IP inside `rules[].host`) so it matches the bare `10.171.24.201` Host header as well as `codesage.local` (`/etc/hosts` → .201).

#### Post-Reboot Network Recovery + CoreDNS Stale-Upstream Fix (2026-09-26)

- After the reboot only the USB adapter is up: **static IP `10.171.24.246/24`** (gw/DNS `10.171.24.212`) on `enp0s20f0u2` via NetworkManager; WiFi `wlp2s0` (whose old address `10.103.145.245` k3s had auto-detected as node IP → MetalLB speaker bind crash) stays down.
- k3s node IP pinned **outside the repo**: `/etc/rancher/k3s/config.yaml` → `node-ip: 10.171.24.246`. Re-plugging the adapter needs no config changes — ingress (`.201`) and the tunnel URL are adapter-independent.
- **Stale `.201` root cause**: `ingress-nginx-controller` Service had lost `spec.selector` (a client-side `kubectl apply` of `ingress-nginx-patch.yaml` — which had no selector — wiped it) → EndpointSlice frozen on a dead pod IP → kube-proxy DNAT → `No route to host` while all pods were Running. Fix: selector restored via `kubectl patch` **and** now present in `infrastructure/k8s/base/ingress/ingress-nginx-patch.yaml` with a comment on the three-way-merge trap. **Diagnostic rule**: pods Running + service unreachable → check `kubectl get svc -o jsonpath='{.spec.selector}'` *before* touching pods (recreating pods cannot fix a selector-less Service).
- **OAuth `ConnectTimeout` (pods only)**: CoreDNS (`dnsPolicy: Default`, `forward . /etc/resolv.conf`) had the dead WiFi resolver baked into its old pod resolv.conf → external DNS `SERVFAIL` in every pod while the host resolved fine → httpx connect timeout during the GitHub code exchange (`OAuth flow failed: ConnectTimeout: `). Fix: recreate the CoreDNS pod so kubelet regenerates resolv.conf from the node's current resolver — `kubectl delete pod -n kube-system -l k8s-app=kube-dns`. Verified from backend + worker pods: github.com, api.github.com, api.groq.com, Gemini, in-cluster SonarQube all resolve <0.05 s.
- Recovery verified green: `.201` health + SPA 200, `codesage.local` 200, ClusterIP `10.43.161.112` 200, NodePort `127.0.0.1:31189` 200, worker listening on `review-requests`, MetalLB announcing `.201`.
- **RECURRED 2026-09-28 after another node reboot (20:28)**: the CoreDNS *container* restarted on boot and its sandbox `resolv.conf` was re-snapshotted from the node's `/etc/resolv.conf` **at that instant — which still held the dead WiFi DNS `10.103.145.73`** (NetworkManager boot-order), while the node later settled on `10.171.24.212` (USB). Symptom: internal cluster DNS fine, external DNS `i/o timeout` from *all* pods → Keycloak GitHub broker code exchange failed with `UnknownHostException: github.com` → user-facing "Unexpected error when authenticating with identity provider" (authorize + callback had worked; only the server-side token exchange needed external DNS). **Fix: `kubectl delete pod -n kube-system -l k8s-app=kube-dns`** (new sandbox snapshots current resolver) — verified `github.com` resolves from backend/worker/keycloak pods. Durable options if it recurs: disable the WiFi profile's autoconnect (`nmcli con mod <wifi> connection.autoconnect no`) so boot-time resolv.conf never carries `10.103.145.73`, or pin CoreDNS `forward` via the k3s `coredns-config` ConfigMap.

#### tp3 Live Test — Review Posted on GitHub; App UI Showed Nothing (2026-09-26)

User's manual test on `Wael-BenHariz/tp3` PR #1 (times UTC, reconstructed from `webhook_events` + worker logs + `watched_repos.updated_at`):

1. **21:13:56 `closed`** → processed (action skipped after PR-state update); **21:14:22 `reopened`** → **not queued** — tp3 was still disabled in `watched_repos` → handler returned `ignored: repo not enabled` (marks the event processed).
2. **21:17:31** — user enabled tp3 in the app UI (`watched_repos.updated_at`).
3. **21:18:54 `closed`** + **21:19:03 `reopened`** → queued → review row `completed` (`overall_severity=error`, `github_review_id=5327492848`, summary 1457 chars, 6 `review_comments`).
4. **21:21:07** review **posted on GitHub**: [`#pullrequestreview-5327492848`](https://github.com/Wael-BenHariz/tp3/pull/1#pullrequestreview-5327492848), author `codesage-ai-bot[bot]`, `state=COMMENTED`, body = stored summary.
- Pipeline trace: installation-token file fetch (`src/code.py@cbd2c5d8`) → SonarQube project create/scan/poll → 5 specialists → synthesis → `POST .../pulls/1/reviews` → 200.
- **"No comment posted" was two separate things**: (a) the first attempt correctly predates enabling tp3 (ignored by the watch gate), and (b) the frontend calls `GET /api/v1/repositories/Wael-BenHariz/tp3` → **404** (no by-full-name route exists), so the app UI shows no review history — the comment is on GitHub under the PR conversation. Inline `pull_request_review_comment`s are never posted by design; only the summary review body.
- This run: 4/5 specialists succeeded — **`style` failed** (`unparseable LLM response after 2 attempts`: gpt-oss-120b answered with raw Python instead of JSON) so synthesis flagged the review partial; `security` recovered on attempt 2, `test_coverage` retried an HTTP 429.

#### Keycloak Identity Migration + Live Verification (2026-09-28, uncommitted on `sonarqube-k3s`)

Replaced the custom GitHub OAuth + HS256 JWT auth with **Keycloak 24.0.5 as identity/token authority** (GitHub OAuth App is now only a Keycloak social-login broker); GitHub App install/webhook/review flow untouched.

**Implementation (per user's 10-point spec)**:
- k8s (`infrastructure/k8s/base/keycloak/`): realm ConfigMap `codesage-realm` (realm JSON: roles SUPER_ADMIN/DEVELOPER/GUEST + groups, GitHub IdP + `github-claims` scope + 3 IdP mappers, clients `codesage-backend` confidential + `codesage-angular` public PKCE S256, seed superadmin), `keycloak-secret.yaml` gitignored (`keycloak-secret.example.yaml` committed), PVC, `keycloak-db-init` job (TTL 600 s — re-apply to recreate), deployment, service, ingress `/auth`; backend secret gains KEYCLOAK_*.
- Backend: `security/keycloak.py` (JWKS fetch + RS256 decode, issuer from `KEYCLOAK_PUBLIC_URL`, `azp`-based audience), `security/roles.py` (derive SUPER_ADMIN > GUEST > DEVELOPER, synced from `realm_access.roles` every request), route guards (`get_current_user` reads / `require_developer` mutations / `require_super_admin` `/users`), rewritten `auth.py` incl. `GET /auth/keycloak/config`; migration 008 (`keycloak_id`, `role`); HS256 `jwt.py` deleted; removed `/auth/refresh`, `/auth/github(+callback)` (verified 404). pytest 23/23; ruff/black clean on touched files (mypy/bandit findings pre-existing).
- Frontend: `keycloak-angular@15.3.0` + `keycloak-js@24`, PKCE S256, `KeycloakBearerInterceptor` DI + `withInterceptorsFromDi()`, `RoleGuard`, `idpHint: 'github'` on every login; all gates green (41/41 tests, format, lint, type-check, build).

**Live-verification debugging (root causes found & fixed)**:
- **KC 24 admin bootstrap** uses legacy `KEYCLOAK_ADMIN`/`KEYCLOAK_ADMIN_PASSWORD` — `KC_BOOTSTRAP_ADMIN_*` (KC 25+) is silently ignored in 24.0.5 → no master admin user.
- **In-cluster JWKS 404**: Keycloak runs `--http-relative-path=/auth`, so `KEYCLOAK_URL` (server-side JWKS base) must be `...svc.cluster.local:8080/**auth**`. Fixed default in `config.py` + `secret.yaml` + `secret.example.yaml` (was missing `/auth` → every token 401 "Invalid or expired token").
- **Realm import shipped without default client scopes**: handcrafted JSON listed `defaultClientScopes: [profile, email, roles, ...]` but only defined `github-claims` → import warnings "Referenced client scope doesn't exist" → tokens had `realm_access.roles: None` → every user fell back to DEVELOPER (guards inert). Fix: export `profile/email/roles/web-origins/acr` from the master realm via admin REST, **strip `protocolMappers[].id`** (mapper ids are globally unique — copying master's ids → `constraint_pcm` duplicate-key 409s), create + attach to both clients, and bake the same reps into the ConfigMap JSON. Fresh re-import verified clean (no scope warnings).
- **Vanilla Keycloak does NOT resolve env placeholders in realm JSON**: `${env.GITHUB_CLIENT_ID}` survived import and blew up broker login with `IllegalArgumentException: Path parameter not provided env.GITHUB_CLIENT_ID` (UriBuilder) → 502 "Could not send authentication request to identity provider". Fix: placeholders renamed to `${GITHUB_CLIENT_ID}`/`${GITHUB_CLIENT_SECRET}`/`${KEYCLOAK_CLIENT_SECRET}` + a **`realm-templating` init container** (postgres:15-alpine, `envsubst` with an explicit var list, `sed` fallback, fails if a placeholder survives) rendering the ConfigMap into an emptyDir at `/opt/keycloak/data/import`. Secrets stay in the k8s Secret, never in git.
- **"Account is not fully set up" on ROPC**: default user profile requires `firstName`+`lastName`+`email` — seed superadmin now carries them in the realm JSON.
- **Broker callback NPE → "Unexpected error when authenticating with identity provider"**: two stacked causes seen live (2026-09-28). (a) Node reboot → CoreDNS sandbox snapshotted the dead WiFi resolver → `UnknownHostException: github.com` on the server-side code exchange (fixed by recreating the CoreDNS pod — see network-recovery section). (b) After DNS worked, `NullPointerException ... this.text is null` in `JsonUtils.splitClaimPath` — the 3 GitHub IdP mappers used config key **`claim.name`** but `AbstractClaimMapper.CLAIM = "claim"` (KC 24 Attribute Importer reads `claim`), so `getConfig().get("claim")` → null. Fixed live via admin REST `PUT /admin/realms/codesage-realm/identity-provider/instances/github/mappers/{id}` (note the **`instances`** path segment; GET-single/mapper-list without it 404s; master admin ROPC tokens are short-lived — re-mint per call batch) and in the ConfigMap source (only the `identityProviderMappers` blocks — protocol mappers in `github-claims` correctly keep `claim.name`). `GitHubIdentityProvider.extractIdentityFromProfile` stores the `/user` profile into `USER_INFO`, so the mappers resolve `login`/`id`/`avatar_url` once the key is right.
- **ROPC smoke lever**: `directAccessGrantsEnabled` toggled on `codesage-angular` via full-representation GET→PUT (top-level field is what the token endpoint checks; `attributes['direct.grants.enabled']` is NOT), smoke, then reverted to default **false**. PKCE `S256` attr preserved.
- **App-DB JIT edge**: realm re-creation changes superadmin `sub` → old row keeps `login='superadmin'` → JIT insert hits `uq_users_login` → IntegrityError mapped to **401** (looked like token failure). Deleting the stale row fixed it; adopt-by-`github_id` protects GitHub logins.
- Realm re-import = `DELETE /admin/realms/codesage-realm` (admin REST) + pod restart (import strategy is `IGNORE_EXISTING`). Each re-import = new signing keys (backend kid-miss → force JWKS refetch path verified working) + new sub (clean stale `users` row).

**Verification (all green)**: admin bootstrap (master ROPC) ✓; realm import clean ✓; superadmin ROPC token `realm_access.roles=[SUPER_ADMIN]` → `GET /auth/me` 200 `role=SUPER_ADMIN` → `GET /users` 200 ✓; GUEST test user → `/auth/me` `role=GUEST` → `/users` **403**, `DELETE /settings/llm` **403** ✓; `/auth/me` no token → 401; `/auth/keycloak/config` → `{url: .../auth, realm: codesage-realm, clientId: codesage-angular}`; webhook bad HMAC → 401; **broker chain**: auth endpoint (PKCE enforced) → `/broker/github/login` → 302 `github.com/login/oauth/authorize?client_id=Ov23liodWJBNCDWEOFkr&redirect_uri=http://10.171.24.201/auth/realms/codesage-realm/broker/github/endpoint` (proves the exact GitHub callback URL); `kubectl kustomize base/` OK; backend health 200. Smoke helpers: `/tmp/opencode/kc_smoke.py` (+ gotcha: pass JSON bodies via `jdata=`, not `data=json.dumps(...)` — double-encoding → 400/415 confusion).

#### repo-tenant-service — one enabled repo = one k8s namespace (branch `feat/repo-tenant-service`)

New Spring Boot 4.0.3 / Java 21 microservice (`repo-tenant-service/`, package `com.codesage.repo`) ported from the faas reference (which was fully reverted first — 5 unpushed commits reset, clean at `4189449`), across 6 commits (`c6ea5e3` skeleton → `3835dc0` domain → `c3a6f7e` flow → `065860b` tests → `5b8fb7b` backend hook → `b557573` k8s deploy + smoke fixes → docs):

- **API**: `POST /api/v1/repos/internal/enable|disable` + `GET /internal/namespaces` (`X-Service-Token`, permitAll + `InternalServiceFilter`); `GET /repos`, `/repos/{id}`, `/repos/{id}/status` (Keycloak JWT, multi-issuer allow-list). camelCase payloads. Enable = upsert + idempotent (retries a FAILED provisioning); disable = namespace delete **then** row delete (row kept on K8s failure), unknown repo → `status: ABSENT`.
- **Shared `codesage` DB**: `repo_tenants` created by backend **Alembic 009**; service JPA `ddl-auto: none` (H2 create-drop only in tests). `owner_user_id` UUID FK → `users` ON DELETE SET NULL; `repo_id` BIGINT matches `watched_repos`.
- **Defaults via ConfigMap** (the required fallback): `QUOTA_SERVICE_URL` empty by default ⇒ `QuotaClient` short-circuits with **no network call**; any URL set ⇒ catch-all fallback to `DEFAULT_*` (cpu/memory/totals/functions/pods) from ConfigMap `repo-tenant-config`. Redis has a lenient `CacheErrorHandler` (down = no cache, never a failed request).
- **Backend hook** (transition-diff, fire-and-forget `asyncio.gather(return_exceptions=True)`): selection endpoint snapshots `previously_enabled` before mutating then fires enable/disable after commit; `installation_repositories/removed` webhook tears down namespaces of removed repos (row kept `enabled=False` for audit). `config.py`: `REPO_TENANT_SERVICE_URL` (in-cluster DNS default), `REPO_TENANT_INTERNAL_TOKEN`, `REPO_TENANT_TIMEOUT_SECONDS` (3.0).
- **k8s** (`infrastructure/k8s/base/repo-tenant-service/`): Deployment (port 8085, `imagePullPolicy: Never`, probes `/actuator/health`), ClusterIP Service, ConfigMap, gitignored `secret.yaml` (`INTERNAL_SERVICE_TOKEN` = backend `REPO_TENANT_INTERNAL_TOKEN`), ServiceAccount + least-privilege ClusterRole/Binding (namespaces CRUD; resourcequotas+limitranges); wired into base kustomization, ingress `/api/v1/repos` rule before `/api`, `build-and-deploy.sh` builds/imports/rolls the image, APPLY_ORDER Step 8b.
- **Two bugs found only by running the built image** (unit tests couldn't see either): `spring-boot-starter-actuator` was missing (inherited from faas — `/actuator/health` fell through to the static-resource handler and 500'd ⇒ probes would never pass) and `GlobalExceptionHandler`'s generic 500 handler swallowed exceptions without logging (now logs method+URI+stack).
- **Verified**: `mvn test` 28/28 (Docker Maven, no Java on host); backend pytest 63/63 (8 new hook tests); `kubectl kustomize` renders 30 objects with correct scoping/path order/token; image smoke against live Postgres/Redis → health UP, prometheus 200, internal endpoint 200/401 with/without token; `alembic upgrade head` 006→009 on local DB.



## Known Gaps

- GitHub App `contents` permission is read-only — the App cannot create branches/commits (403 on `git/refs`); PR creation and review posting work (`pull_requests: write`). Raise it in the App settings only if commit-based test fixtures are ever needed.
- Legacy `/repositories/github` + `/repositories/connect` still require `github_installations` rows (created only by `/repositories/installations/sync` or webhooks) — the signed-state install callback does not create them; post-install repo selection uses the `/github/*` endpoints instead
- GitHub App *Setup URL* (external GitHub App setting, not versioned in this repo) must point at `/api/v1/auth/github/app/callback` — if missing or wrong, the install callback never fires
- `frontend/Dockerfile.dev` does not exist but is referenced by the docker-compose `frontend` service
- `infrastructure/postgres/init.sql` and monitoring configs referenced by docker-compose/CI still don't exist — `docker-compose --profile database up` will fail on the missing `init.sql` mount (`infrastructure/k8s/` for the k3s deployment does exist)
- `infrastructure/k8s/base/backend/secret.yaml` is **filled with real credentials** (GitHub OAuth + App key, Groq/Gemini keys, SonarQube token, `10.171.24.201` CORS/callback URLs) and is now **gitignored** — the committed template is `secret.example.yaml` (`cp secret.example.yaml secret.yaml` to deploy). Never `git add -f` the filled file.
- **Frontend repository detail calls a route that doesn't exist**: the app requests `GET /api/v1/repositories/Wael-BenHariz/tp3` → **404** (backend only exposes `GET /repositories`, `GET /{id}`, `GET /{id}/detail` by UUID) — so the UI shows no PR/review history even when reviews post to GitHub (this is why the tp3 test above *looked* comment-less).
- **Credentials validated in-cluster (this session)**: GitHub App JWT auth → 200 with 2 installations (`164169573` → Wael-BenHariz, `133405090` → CODESAGE-AI-bot); Groq `openai/gpt-oss-120b` completion → 200 "OK" (reasoning model — give generous completion tokens); Gemini key → 200 (50 models). OAuth client id/secret not independently validated (needs the callback URL configured first).
- **GitHub-side settings now configured by the user (this session)**: GitHub App authorization callback + **Setup URL** = `http://10.171.24.201/api/v1/auth/github/app/callback`; **Webhook URL** = `.../webhooks/github` with secret `CODESAGEsecret`. Remaining caveat: `10.171.24.201` is private — browser-side OAuth/Setup redirects work on the LAN, but **live webhook deliveries from github.com need a public tunnel** (cloudflared/ngrok); the E2E above delivered its webhook by direct POST to the ingress.
- **PENDING manual step (Keycloak migration)**: update the GitHub **OAuth App** callback URL on github.com to the Keycloak broker endpoint — `http://10.171.24.201/auth/realms/codesage-realm/broker/github/endpoint` (proven as the `redirect_uri` in the live authorize URL; the old `.../api/v1/auth/github/callback` no longer receives anything). Without it, GitHub logins fail at GitHub with "redirect_uri is not associated with this application".
- **Browser login smoke not executed (2026-09-28)**: desktop browser was not connected to the session, so the SPA → Login → GitHub-broker click was only proven via the curl redirect chain (auth → broker → github.com authorize). Verify manually: open `http://10.171.24.201`, click Login, confirm redirect to github.com (stop before credentials).
- **JIT provisioning maps any failure to 401 "Invalid or expired token"**: an `uq_users_login` collision (e.g. stale `users` row left over after a Keycloak realm re-import changes the user's `sub`) surfaces as a token error, not a provisioning error — the misleading 401s during live verification were this, not JWKS/decode issues. Console-only users (superadmin) have no `github_id` to adopt on, so the stale row must be deleted manually.
- SonarQube runs in-cluster (namespace `sonarqube`, service DNS `sonarqube-sonarqube.sonarqube.svc.cluster.local:9000`); the k8s Secret uses that DNS name while host `backend/.env` uses the ClusterIP — cluster DNS does not resolve from the host
- Repo-wide lint debt is pre-existing: ruff 321 / mypy 47 / black 48 files (touched files pass; unrelated to this session's changes)
- **Specialists can fail on unparseable LLM output**: `openai/gpt-oss-120b` sometimes answers a refinement prompt with raw Python instead of a JSON object → `base_agent` extraction finds no `{...}` → agent fails after 2 retries → review posted as partial ("One of five specialist agents failed"). Observed on `style` (tp3 test); `security` recovered on attempt 2; `test_coverage` hit Groq HTTP 429 (retry succeeded). Possible hardening: a "reply with JSON only" re-ask, or treating unparseable output as zero issues instead of a failure.
- **Backend API app-log lines are invisible**: `kubectl logs deploy/codesage-backend` only shows uvicorn access lines — `app.*` `logger.info` (e.g. webhook queued/ignored/skipped decisions) is dropped because the API process never configures a root handler (the worker does). Webhook outcomes currently have to be reconstructed from DB rows.
- Docker Compose frontend service uses Next.js artifacts: `NEXT_PUBLIC_*` env vars and `.next/` volume, but frontend is Angular — copy-paste error in compose file
- CI `test` job sets `JWT_SECRET` env var, but config expects `SECRET_KEY` — name mismatch
- CI references `pytest-mock`/`httpx` test deps and `--cov=codesage` (package name doesn't match module layout `app.*`)
- Monaco Editor diff view not yet integrated (placeholder in PR detail page)
- Review preferences and notification settings in settings page are UI-only (no backend persistence yet)
