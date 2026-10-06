# CodeSage

**AI-powered code review platform with GitHub integration.**

CodeSage analyzes pull requests with static analysis (SonarQube + Semgrep), refines the findings through a **5-agent LLM pipeline**, and posts a single consolidated summary review back to GitHub. Identity is handled by **Keycloak** (GitHub login via its social-login broker), and organizations control how reviews are published with a per-org **staged / auto** posting mode.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Review Pipeline](#review-pipeline)
- [Static Analysis](#static-analysis)
- [Authentication & Roles](#authentication--roles)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Frontend](#frontend)
- [Microservices](#microservices)
- [Database](#database)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
- [Testing & Linting](#testing--linting)
- [Docker Compose Profiles](#docker-compose-profiles)
- [GitHub & Keycloak Setup](#github--keycloak-setup)
- [CI/CD Pipeline](#cicd-pipeline)
- [Deployment (k3s)](#deployment-k3s)
- [Documentation](#documentation)
- [Known Gaps](#known-gaps)
- [License](#license)

---

## Overview

CodeSage watches the repositories you enable, reacts to GitHub `pull_request` webhooks, and runs an asynchronous review pipeline:

1. **Static analysis** runs in parallel — SonarQube (sonar-scanner) and Semgrep (via a dedicated microservice) — with full fault isolation: either engine failing never fails the review.
2. Findings from both tools are **normalized and merged** into a single unified schema (with cross-tool dedupe markers and snippet enrichment).
3. The unified findings feed **5 specialist LLM agents** (Security, Complexity, Performance, Style, Test Coverage) that run in parallel, each seeing only its domain slice.
4. An **OrchestratorAgent** deterministically merges their results (dedupe by file+line, strongest severity, exact statistics) and makes one summary-only LLM call.
5. **One summary review** is posted to GitHub (`event=COMMENT`, no inline comments) — or parked as `ready_to_post` when the org runs in **staged** mode.

Repository access comes from a **GitHub App installation**; user identity comes from **Keycloak** (GitHub is the login broker). Users can configure their own LLM provider (Groq, OpenAI, Anthropic, Gemini, Ollama) per account, encrypted at rest.

## Key Features

- **Multi-engine static analysis** — SonarQube + Semgrep in parallel, results persisted per review and readable via `GET /reviews/{id}/scan-report`.
- **5-agent LLM review pipeline** — specialist agents run concurrently with per-agent temperature control, failures degrade to a *partial* review instead of breaking it.
- **Single summary review on GitHub** — deterministic merge + one LLM summary; no comment spam.
- **Staged or auto posting** — per-org `posting_mode`: `staged` parks reviews until an admin approves via `POST /reviews/{id}/post` (row-lock protected against double-posting), `auto` posts immediately.
- **Per-user LLM settings** — bring your own provider/model/API key; stored encrypted with Fernet, testable via `POST /settings/llm/test`, default Groq `openai/gpt-oss-120b`.
- **Keycloak identity** — RS256/JWKS validation, GitHub OAuth broker login, four-role model (`PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER`, plus `NONE`), org-scoped membership with fail-closed defaults.
- **Organizations & invitations** — org settings, role-based invitations with SHA-256 token hashing and rate limiting, platform-level settings.
- **Review workflow** — resolve / dismiss / restore comments, reviewer verdicts (`validate`), summary editing before posting, retry for failed reviews.
- **Guided onboarding UI** — help popovers from a single-source copy module, public `/help` page, role-aware navigation, four-state rendering (loading/empty/error/success) everywhere.
- **Tenancy** — enabling a repo calls `repo-tenant-service` (Spring Boot) to provision one k8s namespace per enabled repository.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ / FastAPI |
| Database | PostgreSQL 15+ (SQLAlchemy async, Alembic migrations) |
| Cache/Queue | Redis 7+ / BullMQ review queue |
| Auth | Keycloak 24 (RS256/JWKS; GitHub OAuth App used only as login broker) |
| AI | Per-user LLM via `app/services/llm_client.py` (Groq default; openai/anthropic/gemini/ollama) |
| Static analysis | SonarQube (in-cluster) + Semgrep (`services/semgrep-service/`) |
| Tenancy | Spring Boot 4.0.3 / Java 21 (`repo-tenant-service/` — one enabled repo = one k8s namespace) |
| Frontend | Angular 17+ (standalone components, SCSS, `keycloak-angular` PKCE) |
| CI/CD | GitHub Actions → AWS EKS (blue-green); k3s for local/cluster deploys |
| Monitoring | Prometheus, Grafana, Jaeger (compose `monitoring` profile) |

## Architecture

```
                        ┌──────────────────────────────┐
                        │   GitHub                     │
                        │  webhook ──► App install      │
                        └──────┬───────────────▲────────┘
                               │ PR event      │ summary review (COMMENT)
                               ▼               │
┌──────────────┐   ┌───────────────────────┐    │
│  Angular SPA │◄─►│  FastAPI API (:8000)  │    │
│   (:4200)    │   │  /api/v1/*            │    │
└──────┬───────┘   └───────┬───────────────┘    │
       │ Keycloak (PKCE)   │                    │
       ▼                   ▼                    │
┌──────────────┐   ┌───────────────┐   ┌────────┴────────┐
│  Keycloak 24 │   │  PostgreSQL   │   │  BullMQ worker  │
│ GitHub broker│   │  (asyncpg)    │   │  review_processor│
└──────────────┘   └───────────────┘   └───┬────────┬────┘
                                    Redis ◄┘        │
                                          ┌─────────▼──────────┐
                          parallel        │ SonarQube  Semgrep │
                          static analysis │ (scanner)  (svc)   │
                                          └─────────┬──────────┘
                                                    ▼
                                     normalized unified findings
                                                    ▼
                              5 specialist agents (parallel LLM calls)
                                                    ▼
                              OrchestratorAgent → single summary review
```

Supporting services:

- **`repo-tenant-service`** (Spring Boot): `POST /api/v1/repos/internal/enable|disable` fired best-effort (3 s timeout, failures swallowed) when repo selection changes.
- **`semgrep-service`** (FastAPI): wraps the `semgrep` CLI behind `POST /scan` (+ `/healthz`, `/readyz`).

## Review Pipeline

Detailed flow (also documented in `AGENTS.md` → *Multi-Agent Review Architecture*):

1. **Webhook** `POST /api/v1/webhooks/github` — HMAC verified with `GITHUB_WEBHOOK_SECRET`.
   - bad signature → `401`; unknown event/action → `{"status":"skipped"}`; repo not watched → `{"status":"ignored"}`; queued → `{"status":"queued","review_id":…}`; duplicate delivery → `skipped`.
2. **BullMQ queue** (`review-requests`, concurrency 5) → `app/workers/review_processor.py`.
3. **Idempotency guard** → installation-token PR file fetch.
4. **Parallel static analysis** (SonarQube + Semgrep) with full fault isolation — failures only set `sonar_scan_failed` / `semgrep_scan_failed` flags on the context.
5. **Normalizers** (`normalizers/schema|sonarqube|semgrep|merge|snippets`) unify findings (`also_detected_by` cross-tool marker) and enrich snippets → persisted to `scan_reports` / `scan_findings`.
6. **`ReviewOrchestrator.run()`** — runs the 5 specialists **in parallel** (`asyncio.gather`, staggered by a semaphore, `return_exceptions=True`), tolerating individual failures; each agent sees only its domain slice of `ReviewContext.findings`.
7. **`OrchestratorAgent.synthesize()`** — deterministic merge (dedupe by file+line, strongest severity, exact statistics) + summary-only LLM call.
8. **Post** — one summary review to GitHub (`event=COMMENT`), stored with `github_review_id`. In `staged` mode the review parks as `ready_to_post` (`posted_at` null) until `POST /reviews/{id}/post` (double-post → `409`).
9. **Failure semantics** — a failed specialist → review posted as *partial* (noted in the summary); both analyzers down → "static analysis unavailable" note. The review still completes.

Review statuses: `pending → processing → ready_to_post | completed | failed`.

## Static Analysis

- **SonarQube** (`app/services/sonarqube.py`) — `sonar-scanner` subprocess with a unique per-review project key (always deleted afterwards), configurable timeout/poll interval.
- **Semgrep** (`app/services/semgrep.py`) — `POST {SEMGREP_SERVICE_URL}/scan`, `SEMGREP_TIMEOUT_SECONDS=60`, `SEMGREP_MAX_UPLOAD_BYTES=5 MB`, toggled by `SEMGREP_ENABLED` (set `false` for sonar-only).
- Enriched findings are read back via `GET /api/v1/reviews/{id}/scan-report`.
- Full docs: [`docs/SEMGREP.md`](docs/SEMGREP.md) · plan: [`docs/SEMGREP_INTEGRATION_PLAN.md`](docs/SEMGREP_INTEGRATION_PLAN.md)
- Cluster smoke test: `scripts/smoke_semgrep.sh` (worker→service connectivity, raw scan, backend e2e).

## Authentication & Roles

**Login flow:** SPA reads `GET /api/v1/auth/keycloak/config` → Keycloak authorize (PKCE S256, `keycloak-angular` + `keycloak-js` 24) → GitHub broker → back to SPA. The backend validates RS256 tokens via JWKS (`app/security/keycloak.py`), issuer from `KEYCLOAK_PUBLIC_URL`, audience = `azp`.

> ⚠️ The **GitHub OAuth App callback URL must equal the Keycloak broker endpoint** (`{KEYCLOAK_PUBLIC_URL}/realms/codesage-realm/broker/github/endpoint`) — the old `/api/v1/auth/github/callback` receives nothing.

**Four-role model** (`app/security/roles.py`), precedence **PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER** (an explicit downgrade outranks role grants; fail-closed `NONE` otherwise; GitHub-identity tokens temporarily derive `DEVELOPER`):

| Role | Typical powers |
|------|----------------|
| `PLATFORM_ADMIN` | `/platform` settings, platform user management; read/settings bypass only |
| `ORG_ADMIN` | org settings, invitations, staged-review posting |
| `REVIEWER` | verdicts (`validate`), comment moderation |
| `DEVELOPER` | all review mutations (`require_developer`) |
| `NONE` | read-only blocked from writes → 403 |

Org-scoped access lives in `app/security/org_access.py`: no `org_members` row → uniform `404`, effective role = max(JWT, org member).

## Project Structure

```
codesage/
├── backend/                    # FastAPI API + background workers
│   ├── app/
│   │   ├── api/routes/         # health, auth, users, repositories, github_repos,
│   │   │                       #   pull_requests, reviews, webhooks, settings,
│   │   │                       #   orgs, invitations, platform
│   │   ├── db/models/          # users, watched_repos, reviews, scan_reports, orgs, …
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── security/           # keycloak.py (JWKS/RS256), roles.py,
│   │   │                       #   dependencies.py, org_access.py, encryption.py
│   │   ├── services/           # llm_client.py, static_analysis.py, sonarqube.py,
│   │   │                       #   semgrep.py, normalizers/, scan_report_store.py,
│   │   │                       #   review_orchestrator.py, github.py, github_app.py,
│   │   │                       #   repo_tenant.py, review_posting.py, mail.py, …
│   │   │   └── agents/         # BaseAgent, 5 specialists, OrchestratorAgent, schemas
│   │   ├── workers/            # BullMQ review queue (main, review_queue, review_processor)
│   │   ├── chunker.py          # Diff chunking for large PRs
│   │   ├── diff_parser.py      # GitHub diff parsing
│   │   ├── config.py           # pydantic-settings config
│   │   └── main.py             # FastAPI app entry
│   ├── alembic/                # DB migrations (001–018)
│   ├── tests/                  # ~203 unit tests + 5 e2e + conftest.py + fixtures/
│   ├── Dockerfile / Dockerfile.worker
│   └── requirements.txt
│
├── frontend/                   # Angular 17 app
│   └── src/app/
│       ├── core/               # guards (RoleGuard), interceptors (Keycloak bearer),
│       │                       #   services (one per backend route group) + mappers, models
│       ├── features/           # landing, auth, dashboard, pull-requests, repositories,
│       │                       #   settings (+ org), admin (platform), errors,
│       │                       #   invitations, help
│       └── shared/             # reusable components incl. role-aware site-header
│
├── services/semgrep-service/   # FastAPI microservice wrapping the semgrep CLI
├── repo-tenant-service/        # Spring Boot 4: repo enable → k8s namespace/tenant
├── docs/                       # SEMGREP, UI redesign, screens, gap matrices, release notes
├── scripts/                    # smoke_semgrep.sh, keycloak_migrate_roles.sh, …
├── infrastructure/
│   ├── k8s/                    # k3s base/ + overlays/local + APPLY_ORDER.md + deploy script
│   ├── sonarqube/              # helm-install.sh
│   └── webhook-proxy/          # path-filter proxy + ngrok tunnel (systemd units)
├── docker-compose.yml          # Local dev (PostgreSQL, Redis, PgAdmin, monitoring)
├── AGENTS.md                   # Canonical agent-facing project reference
└── .github/workflows/ci-cd.yaml
```

## API Endpoints

All routes are prefixed with **`/api/v1`** (`API_V1_PREFIX`). Interactive docs (when `ENABLE_API_DOCS=true`): Swagger `/api/docs`, ReDoc `/api/redoc`, OpenAPI JSON `/api/openapi.json`.

### Health — `/health`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | API health check |
| GET | `/health/ready` | Readiness (DB/Redis) |
| GET | `/health/live` | Liveness |

### Authentication — `/auth`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/auth/keycloak/config` | SPA login configuration |
| GET | `/auth/me` | Current Keycloak user (JIT-provisioned) |
| POST | `/auth/logout` | Logout |
| GET | `/auth/github/app/install-url` | GitHub App install URL (state = signed JWT) |
| GET | `/auth/github/app/callback` | App Setup-URL callback → writes installation ID |

### Users — `/users`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/me` · PATCH `/users/me` · DELETE `/users/me` | Self read/update/delete |
| GET | `/users/{user_id}` · GET `/users` | User lookups (admin-gated list) |

### Repositories — `/repositories`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/repositories` | List watched/connected repositories |
| GET | `/repositories/{id}` · `/detail` | Repository details |
| POST | `/repositories/connect` | Connect a repository |
| PATCH | `/repositories/{id}` | Update repository settings |
| POST | `/repositories/{id}/enable` · `/disable` | Toggle the watch switch (fires tenant enable/disable) |
| DELETE | `/repositories/{id}` | Remove repository (204) |
| GET | `/repositories/install-url` | Install-url shortcut |
| POST | `/repositories/installations/sync` | Sync GitHub App installations |
| GET | `/repositories/github` | GitHub-side repo listing |

### GitHub App — `/github`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/github/status` | Installation status |
| GET | `/github/repos` | Available repos from the installation |
| POST | `/github/repos/selection` | Persist repo selection (watch/unwatch) |

### Pull Requests — `/pull-requests`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pull-requests/repository/{repository_id}` | List PRs for a repository |
| GET | `/pull-requests/{id}` | PR details with reviews |
| POST | `/pull-requests/{id}/review` | Trigger a review manually |
| GET | `/pull-requests/{id}/reviews` | Reviews for a PR |

### Reviews — `/reviews`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reviews` | List reviews (filters, pagination) |
| GET | `/reviews/{id}` | Review with comments |
| GET | `/reviews/{id}/status` | Status polling |
| GET | `/reviews/{id}/scan-report` | Unified SonarQube+Semgrep findings |
| POST | `/reviews/{id}/retry` | Retry a failed review |
| POST | `/reviews/{id}/post` | Post a staged review (409 on double-post) |
| PATCH | `/reviews/{id}/summary` | Edit summary before posting |
| PATCH | `/reviews/{id}/comments/{cid}/resolve` | Resolve a comment |
| PATCH | `/reviews/{id}/comments/{cid}/dismiss` · `/restore` | Dismiss / restore |
| PATCH | `/reviews/{id}/comments/{cid}/validate` | Reviewer verdict (REVIEWER+) |
| DELETE | `/reviews/{id}` | Delete review (204) |

### Settings — `/settings`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/settings/llm` | Current LLM settings (API key write-only) |
| PUT | `/settings/llm` | Save encrypted provider/model/key |
| DELETE | `/settings/llm` | Reset to defaults |
| POST | `/settings/llm/test` | Test the configuration |

### Organizations & Invitations — `/orgs`, `/invitations`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/orgs` | Orgs the caller belongs to |
| GET/PUT | `/orgs/{org_id}/settings` | Org settings (incl. `posting_mode`) |
| POST | `/orgs/{org_id}/invitations` | Invite as DEVELOPER/REVIEWER (20/hour/org → 429) |
| GET | `/orgs/{org_id}/invitations` | List invitations |
| DELETE | `/orgs/{org_id}/invitations/{id}` | Revoke |
| GET | `/invitations/{token}` | Public preview (hashed-token lookup) |
| POST | `/invitations/{token}/accept` | Accept (used → 409, expired/revoked → 4xx) |

### Platform — `/platform`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/platform/settings` | Read platform settings |
| PUT | `/platform/settings` | Update platform settings |

### Webhooks — `/webhooks`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhooks/github` | GitHub webhook receiver (HMAC) |

## Frontend

Angular 17 standalone components + SCSS, Keycloak PKCE auth (`keycloak-angular` 15 / `keycloak-js` 24).

**Routes** (`app.routes.ts`):

| Route | Access |
|-------|--------|
| `/` | Public landing (`shell: false`) |
| `/login` | Public |
| `/github/callback` | Public OAuth return |
| `/invite/accept` | Public invitation acceptance |
| `/help` | Public help page |
| `/dashboard` | `ANY_ROLE` |
| `/repositories`, `/repositories/:owner/:repo`, `…/pulls`, `…/pulls/:number` | `ANY_ROLE` reads; mutations `WRITE_ROLES` |
| `/settings`, `/settings/org` | `ADMIN_ROLES` (org) / self settings |
| `/platform` | `PLATFORM_ROLES` only |
| `/not-found`, `/forbidden` | Public error pages |

**Structure** — `core/` (guards, Keycloak bearer interceptor, one service + model + snake→camel mapper per backend route group), `features/` (landing, auth, dashboard, pull-requests, repositories, settings, admin, errors, invitations, help), `shared/` (role-aware site-header, help popovers driven by single-source `shared/help.copy.ts`).

**Conventions** — every data section renders four states (loading / empty / error+retry / success); mutations disable their button while pending; error contract 401 → re-login, 403 → `/forbidden`, 404 → `/not-found`; no `innerHTML` / `bypassSecurityTrust*` anywhere; the backend re-authorizes every request (`can()` only shapes nav cosmetically).

**UI redesign (v0.3.2)** — plan in [`docs/UI_REDESIGN_PLAN.md`](docs/UI_REDESIGN_PLAN.md); design tokens in `styles/_tokens.scss` (frozen palette), route-level app shell, severity-labelled findings, a11y pass. Before/after captures in `docs/ui/before|after/`.

## Microservices

### `services/semgrep-service/`

FastAPI wrapper around the `semgrep` CLI.

| Endpoint | Description |
|----------|-------------|
| `POST /scan` | Run semgrep on uploaded source, return normalized findings |
| `GET /healthz` · `GET /readyz` | Liveness / readiness |

```bash
docker build -t semgrep-service:local services/semgrep-service
docker run --rm -p 8080:8080 semgrep-service:local
```

### `repo-tenant-service/` (Spring Boot 4 / Java 21)

One enabled repository = one k8s namespace. Called best-effort by `app/services/repo_tenant.py`.

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/repos/internal/enable` | Provision tenant for a repo |
| `POST /api/v1/repos/internal/disable` | Tear down tenant |
| `GET /api/v1/repos/internal/namespaces` | List namespaces |
| `GET /api/v1/repos`, `/{id}`, `/{id}/status` | Tenant records & status |

No Java on host — run Maven in Docker:

```bash
docker run --rm -v "$PWD":/workspace -v faas-m2:/root/.m2 \
  -w /workspace/repo-tenant-service maven:3.9.6-eclipse-temurin-21 mvn test -B
```

## Database

PostgreSQL via async SQLAlchemy + Alembic (`backend/alembic/`), driver `postgresql+asyncpg://`.

**Migrations 001–018:**

| # | Migration | Adds |
|---|-----------|------|
| 001 | initial schema | users, oauth_tokens, github_installations, repositories, pull_requests, reviews, review_comments, webhook_events |
| 002 | github installation | `users.github_installation_id` |
| 003 | watched repos | `watched_repos` (THE enable switch) |
| 004–005 | updated_at triggers | schema-drift fixes |
| 006 | review results | `reviews.overall_severity`, `github_review_id`, `review_comments.suggestion` |
| 007 | LLM settings | per-user LLM columns |
| 008 | Keycloak identity | `users.keycloak_id`, `users.role` |
| 009 | repo tenants | `repo_tenants` (for repo-tenant-service) |
| 010–011 | scan reports | `scan_reports`, `scan_findings`, `also_detected_by` |
| 012 | four-role auth | role vocabulary + legacy compat |
| 013 | orgs | `orgs`, `org_members`, `org_settings`, `platform_settings` |
| 014 | staged reviews | `posting_mode`, `posted_at`, `edited_summary`, dismiss columns |
| 015 | comment enrichment | `source_domain` + finding-linkage columns |
| 016 | validations | `review_finding_validations` (`UNIQUE (comment_id, reviewer_id)`) |
| 017–018 | invitations | `org_invitations` (SHA-256 token hash) + `updated_at` hotfix |

## Configuration

Settings live in `backend/app/config.py` (pydantic-settings, loaded from `backend/.env`). Copy `backend/.env.example` → `backend/.env`.

**Required — boot fails without them:**

| Variable | Notes |
|----------|-------|
| `SECRET_KEY` | min 32 chars |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth App (Keycloak broker) |
| `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` | GitHub App (PEM) |
| `GITHUB_WEBHOOK_SECRET` | HMAC verification |
| `STATE_TOKEN_SECRET` | signs install-URL state JWT |
| `GEMINI_API_KEY` | legacy client |
| `GROQ_API_KEY` | default review LLM |
| `LLM_ENCRYPTION_KEY` | valid Fernet key — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

**Notables with defaults:**

```env
# App
API_V1_PREFIX=/api/v1
FRONTEND_URL=http://localhost:4200
CORS_ORIGINS=http://localhost:4200
ENABLE_API_DOCS=false

# Connections (defaults use Docker service names!)
DATABASE_URL=postgresql+asyncpg://codesage:codesage@postgres:5432/codesage
REDIS_URL=redis://redis:6379/0
# local non-Docker: postgres@localhost:5432, redis://:redis_password@localhost:6379/0

# Keycloak (JWKS base must include /auth)
KEYCLOAK_URL=http://localhost:8080/auth
KEYCLOAK_REALM=codesage-realm
KEYCLOAK_CLIENT_ID=codesage-backend
KEYCLOAK_CLIENT_SECRET=...
KEYCLOAK_AUDIENCE=codesage-angular
KEYCLOAK_PUBLIC_URL=
KEYCLOAK_ALLOWED_ISSUERS=[]        # JSON list, must end with /realms/{realm}

# Static analysis
SONARQUBE_URL=http://sonarqube-sonarqube.sonarqube.svc.cluster.local:9000
SONARQUBE_TOKEN=
SEMGREP_ENABLED=true
SEMGREP_SERVICE_URL=http://semgrep-service:8080
SEMGREP_TIMEOUT_SECONDS=60

# LLM
GROQ_MODEL=openai/gpt-oss-120b
LLM_DIFF_CHAR_CAP=16000
AGENT_*_TEMPERATURE=...

# Queue
BULLMQ_REVIEW_QUEUE=review-requests
BULLMQ_CONCURRENCY=5

# Tenancy & mail
REPO_TENANT_SERVICE_URL=...
REPO_TENANT_INTERNAL_TOKEN=dev-token
REPO_TENANT_TIMEOUT_SECONDS=3.0
MAIL_BACKEND=console              # console | smtp (SMTP stubbed, not configured)
```

## Getting Started

### Prerequisites

- Python 3.11+, PostgreSQL 15+, Redis 7+, Node.js 20+
- Docker (for DB/Redis and images)
- GitHub OAuth App + GitHub App credentials
- Keycloak 24 (realm import) and a Groq (or other provider) API key

### 1. Infrastructure

```bash
docker-compose --profile database up -d     # PostgreSQL + Redis
docker-compose ps
```

### 2. Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # fill in credentials
alembic upgrade head                              # migrations 001–018
uvicorn app.main:app --reload                     # API on :8000
```

### 3. Worker (separate terminal)

```bash
cd backend && source venv/bin/activate
python -m app.workers.main
```

### 4. Frontend

```bash
cd frontend
npm install
npm start                                         # dev server on :4200
```

### Optional services

```bash
# Semgrep microservice
docker build -t semgrep-service:local services/semgrep-service
docker run --rm -p 8080:8080 semgrep-service:local

# Debug UIs (PgAdmin, Redis Commander)
docker-compose --profile debug up -d

# Monitoring (Prometheus, Grafana, Jaeger)
docker-compose --profile monitoring up -d
```

## Testing & Linting

### Backend

```bash
cd backend
pytest tests/ -v                 # needs local Postgres `codesage_test` + Redis db 15
pytest tests/ -v -x              # stop on first failure
pytest tests/ --cov=app          # coverage
pytest tests/e2e/                # 5 DB-free e2e tests

ruff check .                     # lint
black --check .                  # format
mypy .                           # types
bandit -r .                      # security scan
```

> `tests/conftest.py` pins **all** env vars (including test Keycloak RS256 keys) **before any `app.*` import** — keep that ordering when adding env config. Repo-wide lint debt is pre-existing (ruff 248 / black 40 / mypy 39); touched files should pass.

### Frontend

```bash
cd frontend
npm run test:ci        # headless Karma/Jasmine (453 tests)
npm run lint           # ESLint
npm run type-check     # tsc --noEmit
npm run format:check   # Prettier (CI gate)
npm run build          # production build
```

### semgrep-service

```bash
cd services/semgrep-service
python -m pytest -v     # smoke test auto-skips if semgrep binary absent
ruff check .
```

### Cluster smoke

```bash
infrastructure/k8s/scripts/build-and-deploy.sh   # build → k3s image import → rollout
scripts/smoke_semgrep.sh                          # worker→semgrep connectivity + e2e
```

## Docker Compose Profiles

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
```

> ⚠️ Known gaps: the `frontend` service references a missing `frontend/Dockerfile.dev` (and stale Next.js artifacts), and `monitoring`/`database` reference missing `infrastructure/postgres/init.sql` + `infrastructure/monitoring/` mounts — see [Known Gaps](#known-gaps).

## GitHub & Keycloak Setup

### 1. GitHub OAuth App (login broker for Keycloak)

1. **GitHub Settings → Developer settings → OAuth Apps → New OAuth App**
   - Homepage URL: `http://localhost:4200`
   - **Authorization callback URL**: `{KEYCLOAK_PUBLIC_URL}/realms/codesage-realm/broker/github/endpoint` ← *must equal the Keycloak broker endpoint exactly*
2. Copy **Client ID** + **Client Secret** into Keycloak's GitHub identity provider (`client-id` / `client-secret`).

### 2. GitHub App (repository access)

1. **Settings → Developer settings → GitHub Apps → New GitHub App**
   - Homepage URL: `http://localhost:4200`
   - **Setup URL**: `http://localhost:8000/api/v1/auth/github/app/callback`
   - Webhook URL: `http://localhost:8000/api/v1/webhooks/github` (+ same secret as `GITHUB_WEBHOOK_SECRET`)
2. Permissions: **Pull requests: Read & write**, **Contents: Read** (read-only — the App cannot create branches; PR creation and review posting work), Metadata: Read.
3. Generate the **private key** (.pem) → `GITHUB_APP_PRIVATE_KEY`; note the App ID → `GITHUB_APP_ID`.
4. Install the App on your org/account; the install ID is stored on `users.github_installation_id` via the install-url callback.

### 3. Keycloak realm

- Realm `codesage-realm`, clients `codesage-backend` (audience `codesage-angular`), GitHub identity provider configured with the OAuth App above.
- Roles live in the realm and are read from the token; migration helper: `scripts/keycloak_migrate_roles.sh`.
- Troubleshooting (realm re-import, stale `users` rows, DNS after node reboot): [`docs/ROLES_SETTINGS_RELEASE.md`](docs/ROLES_SETTINGS_RELEASE.md) and `AGENTS.md` → *Auth & Operations Troubleshooting*.

## CI/CD Pipeline

`.github/workflows/ci-cd.yaml` — order:

```
code-quality → (security-scan + test) → build → deploy-dev / deploy-staging → deploy-production → monitor-deployment
```

- **Branches**: `develop` → dev, `main` → staging → production; `release/**` and `workflow_dispatch` also trigger.
- **Deploy**: AWS EKS, blue-green for production (traffic slot blue→green).
- **Images**: `ghcr.io/<repo>/{frontend,api,worker}`.
- **Versions**: Python 3.12 in CI (local 3.11+), Node 20; test job spins up `postgres:16-alpine` + `redis:7-alpine`.

## Deployment (k3s)

```bash
infrastructure/k8s/scripts/build-and-deploy.sh    # docker build → k3s ctr image import → rollout
                                                  # TAG default v0.2.1-semgrep
infrastructure/k8s/APPLY_ORDER.md                 # correct apply order
infrastructure/sonarqube/helm-install.sh          # SonarQube install
```

- **Secrets**: `infrastructure/k8s/base/backend/secret.yaml` holds real credentials and is **gitignored** — copy `secret.example.yaml` (`cp secret.example.yaml secret.yaml`). Never `git add -f` the filled file.
- **Alembic in-cluster**: use an explicit one-shot Pod manifest with `envFrom: secretRef codesage-backend-secret` (the old `kubectl run … --env-from` was removed in kubectl v1.36).
- **Cache-tag trap**: rebuilt image with the same `$TAG` won't roll out under `imagePullPolicy: IfNotPresent` — evict refs per the runbook in `docs/ROLES_SETTINGS_RELEASE.md` §6.
- **Webhook proxy**: `infrastructure/webhook-proxy/` (path-filter proxy + ngrok tunnel, systemd units).

## Documentation

| Document | Contents |
|----------|----------|
| [`AGENTS.md`](AGENTS.md) | Canonical agent-facing reference (architecture, commands, conventions, troubleshooting) |
| [`docs/SEMGREP.md`](docs/SEMGREP.md) | Semgrep integration full docs |
| [`docs/SEMGREP_INTEGRATION_PLAN.md`](docs/SEMGREP_INTEGRATION_PLAN.md) | Semgrep rollout plan |
| [`docs/UI_REDESIGN_PLAN.md`](docs/UI_REDESIGN_PLAN.md) | v0.3.2 UI redesign (Steps 0–12) |
| [`docs/FRONTEND_SCREENS.md`](docs/FRONTEND_SCREENS.md) | Screens + routes/roles inventory |
| [`docs/FRONTEND_GAP_MATRIX.md`](docs/FRONTEND_GAP_MATRIX.md) | Backend endpoint coverage per screen |
| [`docs/BACKEND_GAPS_FOR_UI.md`](docs/BACKEND_GAPS_FOR_UI.md) | Missing endpoints (never fake them) |
| [`docs/ROLES_SETTINGS_RELEASE.md`](docs/ROLES_SETTINGS_RELEASE.md) | Four roles, org settings, staged reviews, release runbook |
| [`docs/PLAN_ROLES_SETTINGS_STAGED.md`](docs/PLAN_ROLES_SETTINGS_STAGED.md) | Plan behind the roles/settings/staged work |
| `docs/ui/before|after/` | Screenshot captures (15 before / 18 after) |
| `backend/tests/` · `frontend` specs | ~203 + 5 e2e backend tests, 453 frontend tests |

## Known Gaps

- **Docker Compose partly broken**: `frontend` service references a missing `frontend/Dockerfile.dev` with stale Next.js artifacts; `infrastructure/postgres/init.sql` and `infrastructure/monitoring/` don't exist, so `database`/`monitoring` profiles fail on missing mounts.
- **CI `test` job stale**: sets `JWT_SECRET` (config reads `SECRET_KEY`) and runs `--cov=codesage` though the package is `app.*` — with `--cov-fail-under=80` it cannot pass as written.
- **Specialists can fail on unparseable LLM output**: `openai/gpt-oss-120b` sometimes returns raw Python instead of JSON → agent fails after 2 retries → partial review. Groq 429s on the free tier also occur (retries usually recover).
- **Settings page**: review preferences / email toggles are disabled in the UI (gap 4 in `BACKEND_GAPS_FOR_UI.md`) — no backend persistence routes exist yet.
- **Monaco diff view not integrated**: `monaco-editor` + `ngx-monaco-editor-v2` installed but unused (PR detail has no diff viewer).
- **URL segments vs backend keys**: `owner/repo[/pulls/:number]` URLs resolve via search + exact-match (PR-list scan capped at 30 pages); backend exact-lookup routes would remove the scan (gaps 5/6).
- **GitHub App `contents` is read-only** — no branch/commit creation (403 on `git/refs`).
- **Frontend manual E2E pending**: the 12-check manual table awaits test accounts (`docs/FRONTEND_SCREENS.md` §Verification status); automated gates (lint / type-check / format / 453 tests / build / cluster rollout) all passed for v0.3.2.
- **Invitation email is console-only**: default `MAIL_BACKEND=console` prints the link to the backend pod log; SMTP is stubbed, not configured.
- Repo-wide lint debt is pre-existing: ruff 248 / black 40 / mypy 39.

## License

MIT
