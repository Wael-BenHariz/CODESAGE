# AGENTS.md - CodeSage

## Project Overview

AI-powered code review platform with GitHub integration. Analyzes PRs and provides AI-generated feedback using Google Gemini.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ / FastAPI |
| Database | PostgreSQL 15+ (SQLAlchemy async) |
| Cache/Queue | Redis 7+ |
| AI | Google Gemini API |
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
│   │   ├── services/       # GitHub, GitHub App, Gemini clients + review_orchestrator.py
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
├── docker-compose.yml      # Local dev (PostgreSQL, Redis, PgAdmin, monitoring)
└── .github/workflows/      # CI/CD pipeline (ci-cd.yaml)
```

**Note**: `infrastructure/` (K8s manifests, postgres init.sql, monitoring configs) is referenced by docker-compose and CI but does not exist in the repo yet.

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
- **Webhook endpoint**: `POST /api/v1/webhooks/github` — verifies signatures using `GITHUB_WEBHOOK_SECRET`.
- **CORS**: Comma-separated origins in `.env`. Default includes `http://localhost:4200` (Angular dev).
- **Frontend entry**: `frontend/src/main.ts` → `app.component.ts` → `app.routes.ts`
- **Backend entry**: `backend/app/main.py` (FastAPI app)
- **Worker entry**: `backend/app/workers/main.py`

## Multi-Agent Review Architecture

AI reviews run through a multi-agent pipeline (current focus of the `multi-agent` branch):

- **`app/services/review_orchestrator.py`** — `ReviewOrchestrator`: runs 5 specialist agents **in parallel** (`asyncio.gather` with `return_exceptions=True`), tolerates individual agent failures, then synthesizes a final review via `OrchestratorAgent`.
- **`app/services/agents/base_agent.py`** — `BaseAgent`: abstract base handling Gemini invocation + tolerant JSON extraction (regex `{...}` match) from LLM output.
- **Specialist agents** (`agents/specialist_agents.py`): `SecurityAgent`, `ComplexityAgent`, `PerformanceAgent`, `StyleAgent`, `TestCoverageAgent` — each with its own temperature (`AGENT_*_TEMPERATURE` in config).
- **`agents/orchestrator_agent.py`** — `OrchestratorAgent.synthesize()` merges valid agent results into a final `ReviewResult`.
- **Schemas** (`agents/schemas.py`): `ReviewContext`, `AgentResult`, `AgentComment`, `ReviewResult`, `ReviewStatistics`.
- Per-agent token usage is tracked via `GeminiClient.total_usage()` and attached to the final review.

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

## Key Environment Variables

All settings live in `backend/app/config.py` (pydantic-settings, loaded from `backend/.env`). Required (no default): `SECRET_KEY` (min 32 chars), `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (PEM), `GITHUB_WEBHOOK_SECRET`, `STATE_TOKEN_SECRET`, `GEMINI_API_KEY`.

Notables with defaults:
- `GITHUB_APP_SLUG` — used to build the GitHub App installation URL
- `GEMINI_MODEL` (default `gemini-2.0-flash`), `GEMINI_MAX_TOKENS`, `GEMINI_TEMPERATURE`, `AGENT_*_TEMPERATURE` (per-specialist-agent temps)
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

## Known Gaps

- Backend test suite is empty — `pytest` is installed but `backend/tests/` has no files
- Legacy `/repositories/github` + `/repositories/connect` still require `github_installations` rows (created only by `/repositories/installations/sync` or webhooks) — the signed-state install callback does not create them; post-install repo selection uses the `/github/*` endpoints instead
- GitHub App *Setup URL* (external GitHub App setting, not versioned in this repo) must point at `/api/v1/auth/github/app/callback` — if missing or wrong, the install callback never fires
- `frontend/Dockerfile.dev` does not exist but is referenced by the docker-compose `frontend` service
- `infrastructure/` directory (K8s manifests, `postgres/init.sql`, monitoring configs) is referenced by docker-compose and CI but doesn't exist — `docker-compose --profile database up` will fail on the missing `init.sql` mount
- Docker Compose frontend service uses Next.js artifacts: `NEXT_PUBLIC_*` env vars and `.next/` volume, but frontend is Angular — copy-paste error in compose file
- CI `test` job sets `JWT_SECRET` env var, but config expects `SECRET_KEY` — name mismatch
- CI references `pytest-mock`/`httpx` test deps and `--cov=codesage` (package name doesn't match module layout `app.*`)
- Monaco Editor diff view not yet integrated (placeholder in PR detail page)
- Review preferences and notification settings in settings page are UI-only (no backend persistence yet)
