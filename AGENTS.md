# AGENTS.md - CodeSage

## Project Overview

AI-powered code review platform with GitHub integration. Analyzes PRs with static analysis (SonarQube + Semgrep), refines the findings through a 5-agent LLM pipeline, and posts a single summary review back to GitHub. Identity is handled by Keycloak (GitHub login via its social-login broker).

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ / FastAPI |
| Database | PostgreSQL 15+ (SQLAlchemy async) |
| Cache/Queue | Redis 7+ (BullMQ review queue) |
| Auth | Keycloak 24 (RS256/JWKS; GitHub OAuth App used only as login broker) |
| AI | Per-user LLM via `app/services/llm_client.py` (Groq default; openai/anthropic/gemini/ollama) |
| Static analysis | SonarQube (in-cluster) + Semgrep (`services/semgrep-service/`) |
| Tenancy | Spring Boot 4.0.3 / Java 21 (`repo-tenant-service/` — one enabled repo = one k8s namespace) |
| Frontend | Angular 17+ (standalone components, SCSS, `keycloak-angular` PKCE) |
| CI/CD | GitHub Actions → AWS EKS (blue-green) |

## Project Structure

```
codesage/
├── backend/                # FastAPI API + background workers
│   ├── app/
│   │   ├── api/routes/     # health, auth (Keycloak), users, repositories, github, pull-requests, reviews, webhooks, settings
│   │   ├── db/models/      # SQLAlchemy models (users, watched_repos, reviews, scan_reports, …)
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── security/       # keycloak.py (JWKS/RS256), roles.py, dependencies.py, encryption.py
│   │   ├── services/       # llm_client.py (per-user LLM) + static_analysis.py (SonarQube+Semgrep)
│   │   │   │               #   + sonarqube.py / semgrep.py / normalizers/ / scan_report_store.py
│   │   │   │               #   + review_orchestrator.py, github(.py|_app.py), repo_tenant.py
│   │   │   └── agents/     # BaseAgent, 5 specialists, OrchestratorAgent, schemas
│   │   ├── workers/        # BullMQ review queue (main.py, review_queue.py, review_processor.py)
│   │   ├── chunker.py      # Diff chunking for large PRs
│   │   ├── diff_parser.py  # GitHub diff parsing
│   │   └── main.py         # FastAPI app entry
│   ├── alembic/            # DB migrations (001–018)
│   ├── Dockerfile / Dockerfile.worker
│   └── tests/              # ~203 unit tests + e2e/ (5, DB-free) + conftest.py + fixtures/
├── frontend/               # Angular 17 app
│   └── src/app/
│       ├── core/           # guards (RoleGuard), interceptors (Keycloak bearer), services (one per backend route group) + snake→camel mappers, models
│       ├── features/       # landing, auth (incl. github-callback), dashboard, pull-requests, repositories, settings (+ org), errors, invitations, admin (platform)
│       └── shared/         # reusable components incl. role-aware site-header
├── services/semgrep-service/  # FastAPI microservice wrapping the semgrep CLI (POST /scan)
├── repo-tenant-service/    # Spring Boot 4 service: repo enable -> k8s namespace/tenant
├── docs/                   # SEMGREP.md, SEMGREP_INTEGRATION_PLAN.md, UI_REDESIGN_PLAN.md,
│                           #   FRONTEND_SCREENS.md, FRONTEND_GAP_MATRIX.md, BACKEND_GAPS_FOR_UI.md,
│                           #   ROLES_SETTINGS_RELEASE.md + ui/before|after/ screenshots
├── scripts/smoke_semgrep.sh # Cluster smoke: connectivity + scan + backend e2e
├── infrastructure/
│   ├── k8s/                # k3s base/ + overlays/local + APPLY_ORDER.md + scripts/build-and-deploy.sh
│   ├── sonarqube/          # helm-install.sh
│   └── webhook-proxy/      # path-filter proxy + ngrok tunnel (systemd units)
├── docker-compose.yml      # Local dev (PostgreSQL, Redis, PgAdmin, monitoring)
└── .github/workflows/      # CI/CD pipeline (ci-cd.yaml)
```

**Note**: `infrastructure/postgres/init.sql` and `infrastructure/monitoring/` referenced by docker-compose still do not exist (see Known Gaps).

## Developer Commands

### Backend

```bash
cd backend

# Setup
python -m venv venv
source venv/bin/activate       # Linux/Mac  (venv\Scripts\activate on Windows)
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

# Tests (need local Postgres `codesage_test` + Redis db 15; conftest pins all
# env vars — including test Keycloak RS256 keys — before any app import.
# backend/tests/e2e/ is DB-free.)
pytest tests/ -v
pytest tests/ -v -x            # Stop on first failure
pytest tests/ --cov=app        # Coverage

# Lint / Format / Type-check
ruff check .
black --check .
mypy .
bandit -r .                    # Security scan
```

### semgrep-service

```bash
cd services/semgrep-service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -v            # smoke test auto-skips if semgrep binary absent
ruff check .

docker build -t semgrep-service:local services/semgrep-service
docker run --rm -p 8080:8080 semgrep-service:local
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

### k3s deploy / cluster smoke

```bash
infrastructure/k8s/scripts/build-and-deploy.sh   # docker build -> k3s ctr image import -> rollout
                                                 # (TAG default v0.2.1-semgrep; images 127.0.0.1:5000/codesage/*)
scripts/smoke_semgrep.sh                         # worker->semgrep-service connectivity, raw scan, backend e2e (DB-free)
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

- **API prefix**: `/api/v1` (configured via `API_V1_PREFIX` in `.env`).
- **Auth (Keycloak)**: RS256 tokens validated via JWKS (`app/services/security` → `security/keycloak.py`), issuer built from `KEYCLOAK_PUBLIC_URL`, audience = `azp`. Four-role model (v0.3.0) in `security/roles.py`, precedence **PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER** (one-release compat map `SUPER_ADMIN→PLATFORM_ADMIN`, `GUEST→NONE` — removed v0.4.0; an explicit downgrade still outranks role grants); a token with no recognized realm role but GitHub identity claims derives DEVELOPER (F1 temporary, logged), otherwise fail-closed NONE. Org-scoped access in `security/org_access.py`: NONE+write → 403, no `org_members` row → uniform 404, effective role = max(JWT, org member); PLATFORM_ADMIN bypasses membership only on reads/settings (no bypass on dismiss/restore/summary-edit/post/validate). Guards: `get_current_user` (read), `require_developer` (mutations), `require_super_admin` (`/users` = PLATFORM_ADMIN). Users are JIT-provisioned into `users` (`keycloak_id`, migration 008). **Full docs: `docs/ROLES_SETTINGS_RELEASE.md`.**
- **Login flow**: SPA reads `GET /api/v1/auth/keycloak/config` → Keycloak authorize (PKCE S256, `keycloak-angular` + `keycloak-js` 24) → GitHub broker (`/auth/realms/codesage-realm/broker/github/endpoint`) → back to SPA. Frontend: `RoleGuard`, Keycloak bearer interceptor, `idpHint: 'github'` on every login. **The GitHub OAuth App callback URL must equal the Keycloak broker endpoint** — the old `…/api/v1/auth/github/callback` no longer receives anything.
- **Review pipeline**: `POST /webhooks/github` (HMAC via `GITHUB_WEBHOOK_SECRET`) → BullMQ (`BULLMQ_REVIEW_QUEUE`) → `app/workers/review_processor.py`: idempotency guard → installation-token PR file fetch → **parallel static analysis** (SonarQube + Semgrep) → normalizers → persisted scan report → `ReviewContext.findings` → 5 specialist agents → `OrchestratorAgent` synthesis → **one summary review** posted to GitHub (`event=COMMENT`, no inline comments) → stored with `github_review_id`. Per-org `posting_mode` (settings merge, v0.3.0): `staged` parks the review as `ready_to_post` (`posted_at` null) until `POST /reviews/{id}/post` (row lock → double-post 409); `auto` stays byte-identical summary-only.
- **Webhook response contract**: bad signature → `401`; unknown event or non-accepted action → `{"status":"skipped"}`; repo not watched → `{"status":"ignored", …}`; queued → `{"status":"queued","review_id":…}`; duplicate delivery → `skipped`. Event decisions are logged by the worker and (since v0.3.0, root handler in `app/main.py`) also by the API process.
- **Static analysis**: `app/services/static_analysis.py` runs `sonarqube.py` (sonar-scanner subprocess, unique per-review project key, always deleted) and `semgrep.py` (`POST {SEMGREP_SERVICE_URL}/scan`) in parallel with full fault isolation — **either engine failing never fails the review** (only `sonar_scan_failed`/`semgrep_scan_failed` flags on the context). `normalizers/` (schema, sonarqube, semgrep, merge, snippets) unify findings across tools (`also_detected_by`) and enrich snippets; `scan_report_store.py` persists them to `scan_reports`/`scan_findings` (migrations 010/011). Read back via `GET /reviews/{id}/scan-report`. `SEMGREP_ENABLED=false` restores sonar-only. **Full docs: `docs/SEMGREP.md`.**
- **LLM settings**: per-user provider/model/API-key settings stored encrypted (`LLM_ENCRYPTION_KEY`, Fernet — boot fails fast if missing/invalid). `resolve_llm_client()` in `llm_client.py` picks groq/openai/anthropic/gemini/ollama; bad config degrades to the default (Groq, `GROQ_MODEL`). Endpoints: `GET/PUT/DELETE /settings/llm`, `POST /settings/llm/test`.
- **GitHub App**: repository access comes from the App installation (numeric ID on `users.github_installation_id`, migration 002), not OAuth. `watched_repos` (migration 003) is THE enable switch — unwatched repos are `ignored` at the webhook gate. Install button must call `GET /auth/github/app/install-url` (its `state` is a JWT signed with `STATE_TOKEN_SECRET`) and use the returned URL as-is; callback `GET /auth/github/app/callback` writes the installation ID → `{FRONTEND_URL}/github/callback`. The App's external **Setup URL** must point at that callback endpoint.
- **Repo → tenant**: selection changes fire best-effort calls (`app/services/repo_tenant.py`, 3 s timeout, failures swallowed) to `repo-tenant-service` (`POST /api/v1/repos/internal/enable|disable`). Schema `repo_tenants` via Alembic 009 (Spring side runs `ddl-auto: none` — no SQLAlchemy model for it).
- **CORS**: Comma-separated origins in `.env` (default includes `http://localhost:4200`).
- **Entries**: frontend `frontend/src/main.ts` → `app.routes.ts`; backend `backend/app/main.py`; worker `backend/app/workers/main.py`.
- **Frontend (Angular 17, v0.3.2)**: route guards in `app.routes.ts` — `ANY_ROLE` (reads), `WRITE_ROLES` (= `require_developer`), `ADMIN_ROLES` (ORG_ADMIN/PLATFORM_ADMIN + `GET /orgs` membership elevation), `PLATFORM_ROLES` (`/platform` only — deliberately **not** in `ADMIN_ROLES`, so no elevation opens it); public routes carry `data: { shell: false }` (`/`, `/login`, `/github/callback`, `/invite/accept`, `/help`, error pages). `AuthContextService.can()` shapes the shared `site-header` nav cosmetically (the backend re-authorizes every request). One service + model + snake→camel mapper per backend route group (`core/services/`, `core/models/`, `core/services/mappers/`); every data section renders four states (loading / empty / error+retry / success) and mutations disable their button while pending; error contract: 401 → re-login, 403 → `/forbidden`, 404 → `/not-found` (scan-report 404 passes through as "no enrichment"), FastAPI `detail` kept on `ApiError` for inline 422s, LLM API key write-only, no `innerHTML`/`bypassSecurityTrust*` anywhere. Inventories: `docs/FRONTEND_SCREENS.md` (screens + routes/roles), `docs/FRONTEND_GAP_MATRIX.md` (endpoint coverage), `docs/BACKEND_GAPS_FOR_UI.md` (missing endpoints — never fake them). Tests: `npm run test:ci` = 453.
- **UI redesign (v0.3.2, `feat/ui-redesign`, one commit per step)**: plan `docs/UI_REDESIGN_PLAN.md` — Steps 0–12 complete: design tokens (`styles/_tokens.scss`, **frozen palette**; new shades only via `mix()`/`color-mix()`), route-level app shell (sidebar/topbar, role-aware), walkthrough redesigns (dashboard, repositories, review, settings), severity-labelled findings, guided onboarding via `app-help-popover` + single-source `shared/help.copy.ts`, public `/help`, and an a11y/responsive/perf pass (AA fixes listed per commit, `OnPush` on new components, dead `_variables.scss` removed). Before/after captures: `docs/ui/before/` (15) + `docs/ui/after/` (18, 6 public screens × 1440/1024/390). No backend changes; bundle 436.79 → 449.01 kB raw (125.53 transfer).

## Multi-Agent Review Architecture

- **`app/services/review_orchestrator.py`** — `ReviewOrchestrator.run()`: runs 5 specialist agents **in parallel** (`asyncio.gather`, staggered by a semaphore, `return_exceptions=True`), tolerates individual failures, then synthesizes via `OrchestratorAgent`.
- **Findings-driven input**: each specialist sees **only its domain slice** of `ReviewContext.findings` (unified SonarQube + Semgrep findings) via `with_findings()`; the raw diff stays in the context for reference only. Routing rules live in `review_orchestrator.py`.
- **`agents/base_agent.py`** — `BaseAgent`: LLM invocation (`BaseLLMClient`) + tolerant JSON extraction (regex `{...}` match) from LLM output.
- **Specialist agents** (`agents/specialist_agents.py`): `SecurityAgent`, `ComplexityAgent`, `PerformanceAgent`, `StyleAgent`, `TestCoverageAgent` — shared `_SpecialistAgent` base with a `DOMAIN` prompt; per-agent temperature via `AGENT_*_TEMPERATURE` in config.
- **`agents/orchestrator_agent.py`** — `OrchestratorAgent.synthesize()`: deterministic merge of agent results (dedupe by file+line, strongest severity, exact statistics) + a summary-only LLM call — the resulting summary is what gets posted to GitHub.
- **Schemas** (`agents/schemas.py`): `ReviewContext` (incl. `findings`, `sonar_scan_failed`, `semgrep_scan_failed`), `AgentResult`, `AgentComment`, `ReviewResult`, `ReviewStatistics`.
- **Failure semantics**: a failed specialist → review posted as *partial* (noted in the summary); both analyzers down → "static analysis unavailable" note. The review still completes and posts.

## CI/CD Pipeline

Order: `code-quality` → (`security-scan` + `test` in parallel) → `build` → `deploy-dev` / `deploy-staging` → `deploy-production` → `monitor-deployment`

- **Branches**: `develop` → dev env, `main` → staging → production; also `release/**` triggers and `workflow_dispatch`
- **Deploy**: AWS EKS with blue-green for production (traffic slot switch blue→green)
- **Images**: `ghcr.io/<repo>/{frontend,api,worker}`
- **Versions**: Python 3.12 in CI (local 3.11+), Node 20
- **Postgres/Redis services in test job**: `postgres:16-alpine`, `redis:7-alpine`

## Important Conventions

- **Backend linters**: `ruff` (lint), `black` (format), `mypy` (types), `bandit` (security)
- **Frontend linters**: ESLint + Prettier + TypeScript strict checks
- **Frontend CI scripts** (all present in `package.json`): `type-check`, `format:check`, `test:ci` (Karma launcher `ChromeHeadlessCI` — Chrome first, falls back to Edge `msedge.exe` on Windows), `lint`/`lint:fix`, `format`. Template a11y lint errors are fixed in templates, never suppressed.
- **Backend tests** (`backend/tests/`, 22 files ≈ 203 unit + 5 e2e): `conftest.py` sets every required env var (incl. a throwaway RSA key for Keycloak RS256 tokens) **before any `app.*` import** — keep that ordering when adding env config. Full suite needs local Postgres (`codesage_test`) + Redis (db 15); `tests/e2e/` is DB-free.
- **Async database**: Uses `asyncpg` driver (`postgresql+asyncpg://`). Do not use sync SQLAlchemy patterns.
- **Redis has password** in docker-compose: `redis_password`. Local `.env` must match if connecting to Docker Redis.
- **Lint debt is pre-existing**: ruff 248 / black 40 files / mypy 39 repo-wide — touched files should pass, unrelated failures are not yours to fix.

## Auth & Operations Troubleshooting

- **"redirect_uri is not associated with this application"**: the GitHub **OAuth App** callback URL must exactly match the Keycloak broker endpoint — `{KEYCLOAK_PUBLIC_URL}/realms/codesage-realm/broker/github/endpoint` (visible as `redirect_uri` in the authorize URL). The old `/api/v1/auth/github/callback` no longer exists.
- **GitHub App Setup URL** (external GitHub setting, not versioned here) must point at `http(s)://<host>/api/v1/auth/github/app/callback` or the install callback never fires.
- **Keycloak realm re-import** (delete realm via admin REST + pod restart): new signing keys → backend must refetch JWKS (works automatically), and every user's `sub` changes → a stale `users` row can collide and surface as a misleading `401 "Invalid or expired token"` (JIT provisioning maps failures to 401). Delete the stale row; GitHub logins are also adoptable by `github_id`.
- **Pods can't resolve external DNS after a node reboot** (symptom: OAuth/broker exchange times out or `UnknownHostException`): CoreDNS's sandbox `resolv.conf` snapshot is stale — `kubectl delete pod -n kube-system -l k8s-app=kube-dns` to re-snapshot from the node's current resolver.
- **Service unreachable while all pods are Running**: check `kubectl get svc -o jsonpath='{.spec.selector}'` first — a client-side `kubectl apply` of a patch without `spec.selector` wipes it (three-way merge trap; fixed in `infrastructure/k8s/base/ingress/ingress-nginx-patch.yaml`). Recreating pods cannot fix a selector-less Service.
- **Invitation link nowhere to be found**: the default `MAIL_BACKEND=console` delivers nothing — the link is the `mail_console to=…` line in the **backend pod log** (needs the root `logging.basicConfig` in `app/main.py`, v0.3.0). SMTP delivery is stubbed (`MAIL_BACKEND=smtp` + `SMTP_*`), not configured yet.
- **Rebuilt image with the same `$TAG` doesn't roll out**: `imagePullPolicy: IfNotPresent` trusts containerd's cached tag, and this host has no passwordless sudo (`k3s ctr` unusable; `kubectl debug` chroot/nsenter → EPERM). Evict the refs with the `ctr-evict` socket-mount pod, then `rollout restart` — YAML and full runbook in `docs/ROLES_SETTINGS_RELEASE.md` §6.
- **`kubectl run … --env-from` fails** (removed in kubectl v1.36; `APPLY_ORDER.md` example is stale): run Alembic via an explicit one-shot Pod manifest with `envFrom: secretRef codesage-backend-secret` — example in `docs/ROLES_SETTINGS_RELEASE.md` §6.

## Environment Files

| File | Purpose |
|------|---------|
| `.env.example` (root) | Minimal env for tooling |
| `backend/.env.example` | Full backend config template |
| `backend/.env` | Active backend config (gitignored) |

## Database

- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic (config in `backend/alembic.ini`)
- **Default Docker DB**: `postgresql://codesage:codesage@localhost:5432/codesage`
- **Test DB**: `postgresql://codesage:codesage@localhost:5432/codesage_test` (Redis db 15)
- **Migrations on disk**:
  1. `001_initial_schema.py` — users, oauth_tokens, github_installations, repositories, pull_requests, reviews, review_comments, webhook_events
  2. `002_add_github_installation_id_to_users.py` — `users.github_installation_id`
  3. `003_create_watched_repos.py` — `watched_repos` (user repo-selection for reviews)
  4. `004_add_updated_at_to_webhook_events.py` / `005_add_updated_at_to_review_comments.py` — `updated_at` + triggers (schema-drift fix)
  5. `006_add_review_result_columns.py` — `reviews.overall_severity`, `reviews.github_review_id`, `review_comments.suggestion`
  6. `007_add_llm_settings_to_users.py` — per-user LLM settings
  7. `008_keycloak_identity_and_role.py` — `users.keycloak_id`, `users.role`
  8. `009_create_repo_tenants.py` — `repo_tenants` (schema for `repo-tenant-service`)
  9. `010_scan_reports.py` — `scan_reports` + `scan_findings` (static-analysis results per review)
  10. `011_add_also_detected_by_to_scan_findings.py` — cross-tool dedupe marker on findings
  11. `012_four_role_authorization.py` — four-role vocab on `users.role` + legacy compat
  12. `013_orgs_members_settings.py` — `orgs`, `org_members`, `org_settings`, `platform_settings` (+ seed from `github_installations`)
  13. `014_staged_reviews.py` — `reviews.posting_mode/posted_at/edited_summary`, `review_comments.dismissed*`
  14. `015_review_comment_enrichment.py` — `review_comments.source_domain` + finding-linkage columns
  15. `016_review_finding_validations.py` — reviewer verdicts (`UNIQUE (comment_id, reviewer_id)`)
  16. `017_org_invitations.py` — `org_invitations` (SHA-256 token hash only)
  17. `018_org_invitations_updated_at.py` — hotfix: `updated_at` omitted by 017

## Key Environment Variables

All settings live in `backend/app/config.py` (pydantic-settings, loaded from `backend/.env`). **Required (no default, boot fails)**: `SECRET_KEY` (min 32 chars), `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (PEM), `GITHUB_WEBHOOK_SECRET`, `STATE_TOKEN_SECRET`, `GEMINI_API_KEY` (legacy client), `GROQ_API_KEY` (default review LLM), `LLM_ENCRYPTION_KEY` (valid Fernet key — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

Notables with defaults:
- **Keycloak**: `KEYCLOAK_URL` (server-side JWKS base — must include `/auth`), `KEYCLOAK_REALM` (`codesage-realm`), `KEYCLOAK_CLIENT_ID`/`KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_AUDIENCE`, `KEYCLOAK_PUBLIC_URL` (issuer base), `KEYCLOAK_ALLOWED_ISSUERS` (JSON list, must end with `/realms/{realm}`)
- **Static analysis**: `SONARQUBE_URL` (in-cluster DNS default), `SONARQUBE_TOKEN`, `SONARQUBE_ANALYSIS_TIMEOUT`, `SEMGREP_ENABLED` (true), `SEMGREP_SERVICE_URL`, `SEMGREP_TIMEOUT_SECONDS`, `SEMGREP_MAX_UPLOAD_BYTES`
- **LLM**: `GROQ_MODEL` (default `openai/gpt-oss-120b`), `LLM_DIFF_CHAR_CAP` (16000), legacy `GEMINI_MODEL`/`GEMINI_MAX_TOKENS`/`GEMINI_TEMPERATURE`, `AGENT_*_TEMPERATURE`
- **Queue**: `BULLMQ_REVIEW_QUEUE` (`review-requests`), `BULLMQ_CONCURRENCY` (5)
- **Connections**: `REDIS_URL` — **default `redis://redis:6379/0` (Docker service name)**; local non-Docker: `redis://:redis_password@localhost:6379/0`. `DATABASE_URL` — **default `postgresql+asyncpg://codesage:codesage@postgres:5432/codesage` (Docker service name)**; use `localhost:5432` outside Docker.
- **App**: `API_V1_PREFIX` (`/api/v1`), `FRONTEND_URL`, `CORS_ORIGINS`, `GITHUB_APP_SLUG`, `REPO_TENANT_SERVICE_URL` / `REPO_TENANT_INTERNAL_TOKEN` / `REPO_TENANT_TIMEOUT_SECONDS` (3.0)

## Known Gaps

- **Repository/PR URL segments don't match backend keys (worked around)**: `owner/repo[/pulls/:number]` URLs resolve through `GET /repositories?search=` + an exact case-insensitive match (session-cached) and a PR-list scan capped at 30 pages for the number (gaps 5/6 in `docs/BACKEND_GAPS_FOR_UI.md`) — backend exact-lookup routes would remove the scan. The phantom `GET /repositories/{owner}/{repo}` / `GET /repositories/{repoId}/pulls` / `GET /pulls/{owner}/{repo}/{number}` paths are gone (`github.service.ts` deleted, replaced by `repository.service.ts` + `pull-request.service.ts` — API-coverage plan Step 2, `57d2fd6`).
- **Docker Compose is partly broken**: `frontend` service references a missing `frontend/Dockerfile.dev` and uses Next.js artifacts (`NEXT_PUBLIC_*` env, `.next` volume) though the frontend is Angular; `infrastructure/postgres/init.sql` and `infrastructure/monitoring/` don't exist, so the `database` and `monitoring` profiles fail on missing mounts.
- **CI `test` job is stale**: sets `JWT_SECRET` (config reads `SECRET_KEY` — tests only pass because `conftest.py` supplies all env) and runs `--cov=codesage` although the package layout is `app.*` → coverage target doesn't exist (with `--cov-fail-under=80` this job cannot pass as written).
- **Specialists can fail on unparseable LLM output**: `openai/gpt-oss-120b` sometimes answers a refinement prompt with raw Python instead of JSON → `base_agent` extraction finds no `{...}` → agent fails after 2 retries → review posted as partial. Possible hardening: a "reply with JSON only" re-ask, or treating unparseable output as zero issues instead of a failure. Groq HTTP 429s also occur on the free tier (retries usually recover).
- **Settings page**: review preferences and email notification toggles have no backend persistence routes — since frontend v0.3.1 they render **disabled** with a "Not available yet — …nothing here is saved." label (never pretend to save; gap 4 in `docs/BACKEND_GAPS_FOR_UI.md`).
- **Monaco diff view not integrated**: `monaco-editor` + `ngx-monaco-editor-v2` are installed but unused in any component (PR detail still has no diff viewer).
- **Frontend manual E2E pending**: the 12-check manual table was deferred by decision at release time (test accounts not provided yet) — recorded as pending in `docs/FRONTEND_SCREENS.md` §Verification status. It now applies to the redesigned UI (v0.3.2): automated gates (lint / type-check / format / 453 tests / build / cluster rollout) all passed and public screens are captured in `docs/ui/after/`, but the authenticated flows still await test accounts.
- **`infrastructure/k8s/base/backend/secret.yaml` is filled with real credentials** (GitHub OAuth + App key, Groq/Gemini keys, SonarQube token) and is **gitignored** — the committed template is `secret.example.yaml` (`cp secret.example.yaml secret.yaml` to deploy). Never `git add -f` the filled file.
- **GitHub App `contents` permission is read-only** — the App cannot create branches/commits (403 on `git/refs`); PR creation and review posting work (`pull_requests: write`). Raise it in the App settings only if commit-based test fixtures are ever needed.
- Repo-wide lint debt is pre-existing: ruff 248 / black 40 files / mypy 39 (see Important Conventions).
