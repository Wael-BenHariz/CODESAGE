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
├── backend/              # FastAPI API + background workers
│   ├── app/
│   │   ├── api/routes/   # Endpoint handlers
│   │   ├── db/models/    # SQLAlchemy models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── security/     # JWT & auth
│   │   ├── services/     # GitHub & Gemini clients
│   │   └── workers/      # BullMQ review queue
│   ├── alembic/          # DB migrations
│   └── tests/            # pytest suite (currently empty)
├── frontend/             # Angular 17 app
│   └── src/app/
│       ├── core/         # Services, guards, interceptors, models
│       ├── features/     # Feature modules (auth, dashboard, PRs, repos, settings)
│       └── shared/       # Reusable components
├── docker-compose.yml    # Local dev (PostgreSQL, Redis, PgAdmin, monitoring)
└── .github/workflows/    # CI/CD pipeline
```

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
npm run test                   # Karma/Jasmine tests
npm run lint                   # ESLint
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
- **Review queue**: BullMQ on Redis. Reviews are queued as background jobs, processed by `app.workers.main`.
- **GitHub App**: Used for repository access and webhook events (separate from OAuth App).
- **Webhook endpoint**: `POST /api/v1/webhooks/github` — verifies signatures using `GITHUB_WEBHOOK_SECRET`.
- **CORS**: Comma-separated origins in `.env`. Default includes `http://localhost:4200` (Angular dev).
- **Frontend entry**: `frontend/src/main.ts` → `app.component.ts` → `app.routes.ts`
- **Backend entry**: `backend/app/main.py` (FastAPI app)
- **Worker entry**: `backend/app/workers/main.py`

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
- **CI expects** `npm run type-check` and `npm run format:check` in frontend — these scripts are referenced in CI but may not exist in `package.json`. Add them if missing.
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

#### Frontend API Integration
- Mapped backend snake_case to frontend camelCase in `github.service.ts`
- Fixed `repos.filter is not a function` by mapping paginated response correctly
- Added "Switch Account" and "Connect Repository" UI features

#### Frontend Redesign (Industrial Terminal Aesthetic)
- Complete visual overhaul using dark theme with JetBrains Mono and electric green (#00e87b) accents
- Redesigned global styles (`styles.scss`, `_reset.scss`, `_mixins.scss`)
- Redesigned all pages: landing, login, callback, dashboard, repository list, PR list, PR detail, settings
- Dark backgrounds (#0a0a0a, #111111), subtle borders (#1e1e1e), monospace typography throughout

## Known Gaps

- Backend test suite is empty — `pytest` is installed but `backend/tests/` has no files
- Frontend `package.json` missing `type-check` and `format:check` scripts referenced in CI
- Docker Compose frontend service references `.next/` volume (Next.js artifact) but frontend is Angular — likely a copy-paste error in compose file
- Monaco Editor diff view not yet integrated (placeholder in PR detail page)
- Review preferences and notification settings in settings page are UI-only (no backend persistence yet)
