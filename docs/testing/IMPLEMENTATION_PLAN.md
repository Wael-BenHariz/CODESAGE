# CodeSage — Testing Infrastructure Implementation Plan

**Branch:** `feat/testing-infrastructure`
**Owner:** QA Automation (PFE deliverable)
**Scope:** add a complete, repeatable testing stack (unit / integration / E2E / security / performance / reporting) on top of the
existing CodeSage codebase **without modifying application logic, Kubernetes manifests or Keycloak configuration**.

---

## 1. Audit summary (measured, not assumed)

| Area | State found |
|---|---|
| Backend suite | 501 `def test_*` across 40 files in `backend/tests/` (+ 5 `tests/e2e/`), `pytest.ini` (`pythonpath=.`, `asyncio_mode=auto`), `conftest.py` pins every env var before any `app.*` import and truncates all tables per test |
| Frontend suite | 60 `*.spec.ts` (563 Karma specs per project docs), `test:ci` → `ChromeHeadlessCI` |
| CI | single workflow `.github/workflows/ci-cd.yaml` (`.gitignore` whitelists only this file: `.github/workflows/*.yml` is ignored, so **new jobs must be added to this file**) |
| Live environment | k3s namespace `codesage`: frontend, backend, keycloak, postgres, redis, semgrep-service, repo-tenant-service all `Running`; ingress `http://10.171.24.201` |
| Deployed build | `waelbhz/codesage-{frontend,api}:5cf27a57…` == current `HEAD` → selectors under test match this repository |
| Keycloak | realm `codesage-realm`, client `codesage-angular` (public, PKCE, `directAccessGrantsEnabled: true`), `redirectUris: ["http://10.171.24.201/*"]` **only** |
| E2E identities | `e2e-platform` (PLATFORM_ADMIN), `e2e-org-admin`, `e2e-reviewer`, `e2e-developer`, `e2e-none` (∅), `e2e-invitee` (∅) — all exist, verified through a real password grant; subs match `frontend/e2e/.auth/users.json` |
| Keycloak login page | serves a real `username`/`password` form → automatable (the SPA's own button forces `idpHint=github`) |
| SonarQube | `http://10.43.246.4:9000`, UP, v26.9; token identity `admin` with global perms `[admin, gateadmin, profileadmin, provisioning, scan]` → project creation permitted |
| Semgrep | real service `http://10.43.216.224:8080` reachable from the host |
| Toolchain | Docker 29.8.1 (daemon up), node 26, python 3.14, `@playwright/test@1.64.1` already in `node_modules` (absent from `package.json`), chromium-1248 downloaded, npm registry OK, Docker Hub OK |
| Missing | no local Postgres/Redis on `5432`/`6379` (so the existing suite could not run), no `playwright.config.ts`, no E2E specs, no Allure/k6/newman/ZAP wiring, no `docs/testing/`, **no JVM**, no `k6`/`newman`/`allure` binaries |
| Leak risk | `backend/.env.e2e` (holds `E2E_USER_PASSWORD`) is **not** covered by `.gitignore` |

### Recovery note
`backend/tests_integration/__pycache__` and `scripts/e2e/__pycache__` were the only remnants of a previous, deleted
implementation. Their bytecode was inspected: it used exactly the hybrid isolation below (`bootstrap_env.py`,
`provision_keycloak.py`, `seed_local.py`, real-Keycloak `tests_integration/` with markers, fixed seed UUIDs). This plan
**restores and extends** that design instead of inventing a new one.

---

## 2. Test environment and isolation

### 2.1 Architecture

```
                        ┌────────────────────────────────────────────┐
 Playwright / Chromium  │  http://10.171.24.201  (deployed Angular)  │
                        └───────────────┬────────────────────────────┘
                                        │  /auth/**     → real Keycloak (e2e-* users)
                                        │  /api/v1/**   → intercepted by Playwright
                                        ▼
                        ┌────────────────────────────────────────────┐
                        │  http://127.0.0.1:8002  disposable backend │
                        │   ├── codesage_e2e  (Docker Postgres)      │
                        │   └── redis db 14   (Docker Redis)         │
                        └────────────────────────────────────────────┘

 pytest (unit + integration)  → Docker Postgres :55433 `codesage_test` + Redis :56380  (CI parity)
 Sonar benchmark              → Docker sonar-scanner → real SonarQube (project KEPT for screenshots)
 Semgrep benchmark            → real semgrep-service
 ZAP baseline                 → 127.0.0.1:8002 only (+ locally built dist served on :8099)
 k6                           → 127.0.0.1:8002 only
```

**Why the SPA stays on `10.171.24.201`:** that is the only origin present in `redirectUris`/`webOrigins` of the
`codesage-angular` client. Hosting the SPA on `localhost:4200` would require a Keycloak client change, which is
explicitly out of scope. The origin is also same-origin with Keycloak (`/auth`), which removes third-party-cookie
problems for `check-sso`.

**Why `codesage_e2e` and not the dev DB:** Playwright intercepts `/api/v1/**` and replays it against a backend whose
`DATABASE_URL` points at a throwaway Postgres database. The dev `codesage` database is never written to.

### 2.2 Ports (collision-free)

| Port | Owner |
|---|---|
| 8000 | pre-existing local uvicorn (untouched) |
| 4200 | Angular dev server (not used) |
| 5050 | Allure Docker Service |
| 5432 | Docker Postgres `codesage-test-db` (binds **only** `127.0.0.1`) — serves `codesage_test` (pytest) and `codesage_e2e` (E2E) |
| 6379 | Docker Redis `codesage-test-redis` (binds **only** `127.0.0.1`) — db 15 = pytest, db 14 = E2E |
| 8002 | E2E backend (override with `E2E_API_PORT`) |
| 8099 | locally built SPA (static, for ZAP asset checks) |

Port 8001 was already occupied by a pre-existing local listener during the
final stack verification. The disposable API defaults to 8002 and accepts
`E2E_API_PORT` as an override; scripts pass that selection consistently to the
browser proxy, integration tests, ZAP, and k6.

`tests/conftest.py` hard-codes `localhost:5432` / `redis://localhost:6379/15` (kept untouched for CI parity), which is why the
throwaway containers bind the standard ports on loopback instead of custom ones. They are separate containers from any
CodeSage service and are removed by `stop_e2e_stack.sh` / `start-test-deps.sh --down`.

### 2.3 Data isolation rules

* E2E database reset = `DROP`/`CREATE` `codesage_e2e` + deterministic seed (fixed UUIDs) before each suite run.
* pytest keeps the project convention: `TRUNCATE` per test via `tests/conftest.py` (unchanged).
* `tests_integration/` uses its own `conftest.py`, real JWKS, real tokens, and the same `codesage_e2e` schema.
* No production data, no production credentials. Everything secret is read from `backend/.env` / `backend/.env.e2e`
  and never printed, logged, committed, or attached to a report.

---

## 3. Tool contracts (verified before implementation)

| Tool | Contract verified | How it is driven |
|---|---|---|
| **pytest** (+cov, html, async, mock, xdist) | already in use | `scripts/testing/run-backend.sh` |
| **Allure Docker Service** | image `frankescobar/allure-docker-service`, port `5050`, volumes `/app/allure-results` + `/app/default-reports`, `CHECK_RESULTS_EVERY_SECONDS=NONE` + `GET /allure-docker-service/generate-report`, report at `/allure-docker-service/projects/default/reports/latest/index.html`, `--user=$(id -u):$(id -g)` to avoid the known permission issue | `allure-up.sh`, `allure-generate.sh`, `allure-open.sh`, `allure-down.sh` |
| **Playwright** | `@playwright/test@1.64.1`, chromium-1248 present | `playwright.config.ts`, `npx playwright test --ui`, `npx playwright show-report` |
| **Newman** | npm registry reachable → `npx newman` | `scripts/testing/run-newman.sh` |
| **OWASP ZAP** | `zaproxy/zap-stable`, `/zap/zap-baseline.py`, `-r html -J json` | `scripts/testing/zap-baseline.sh` (passive only) |
| **k6** | `grafana/k6` image | `scripts/testing/k6-run.sh` |
| **sonar-scanner** | `sonarsource/sonar-scanner-cli` image; token has `provisioning` + `admin` | `scripts/testing/sonar-benchmark.sh` |

---

## 4. Deliverables

### 4.1 New files

```
docs/testing/IMPLEMENTATION_PLAN.md          # this file
docs/testing/README.md                       # architecture, install, commands, troubleshooting
docs/testing/TEST_PLAN.md                    # strategy, levels, sprint test cases, IDs, status
docs/testing/SCREENSHOT_GUIDE.md             # the 12 screenshots (commands + captions)

scripts/testing/bootstrap_env.py             # generate backend/.env.e2e (random secrets)
scripts/testing/provision_keycloak.py        # verify-only by default; create only if missing (asks first)
scripts/testing/seed_e2e_db.py               # deterministic codesage_e2e seed
scripts/testing/docker_env_file.py            # dotenv → Docker env-file conversion (private temp file)
scripts/testing/start_e2e_stack.sh           # Docker pg/redis + disposable API container :8002
scripts/testing/stop_e2e_stack.sh
scripts/testing/Dockerfile.e2e               # Python 3.14 test-only backend image
scripts/testing/run-integration.sh           # real Keycloak role matrix + reports
scripts/testing/integration-auth.env.sh      # loads ignored E2E identities without printing secrets
scripts/testing/run-backend.sh               # pytest + coverage + html + allure results
scripts/testing/run-playwright.sh
scripts/testing/run-newman.sh
scripts/testing/run-sprint.sh                # 1|2|3|4|all
scripts/testing/allure-up.sh / allure-generate.sh / allure-open.sh / allure-down.sh
scripts/testing/sonar-benchmark.sh           # unique key codesage-benchmark-<uuid>, project KEPT
scripts/testing/sonar-cleanup.sh             # typed confirmation + exact key match
scripts/testing/zap-baseline.sh              # localhost allow-list, passive only, egress assertion
scripts/testing/zap-report.sh
scripts/testing/static-asset-checks.sh       # static checks on locally built dist
scripts/testing/k6-run.sh

testing/postman/CodeSage.postman_collection.json
testing/postman/codesage-local.postman_environment.json      # placeholders only
testing/k6/smoke.js  load.js  stress.js  lib/options.js
testing/zap/rules.tsv
testing/reports/.gitignore

backend/requirements-test.txt
backend/tests/test_contract_webhooks.py
backend/tests/test_worker_lifecycle.py
backend/tests/test_agent_failure_modes.py
backend/tests/benchmark_repo/…               # controlled defects (py + js)
backend/tests/e2e/test_static_analysis_live.py
backend/tests_integration/conftest.py
backend/tests_integration/test_s1_invitations_orgs.py
backend/tests_integration/test_s2_worker_queue.py
backend/tests_integration/test_s3_review_pipeline.py
backend/tests_integration/test_s4_authorization_matrix.py
backend/tests_integration/test_real_keycloak_auth.py

frontend/playwright.config.ts
frontend/e2e/support/{auth.setup.ts,api-proxy.ts,data.ts}
frontend/e2e/pages/{login,dashboard,repositories,pr-detail,reviews,org-settings,platform-admin,invite-accept}.page.ts
frontend/e2e/specs/{sprint1-auth.spec.ts,sprint2-github.spec.ts,sprint3-review.spec.ts,sprint4-admin.spec.ts}
```

### 4.2 Modified files

```
.gitignore                                   # backend/.env.e2e, reports/, playwright-report/, test-results/, e2e/.auth/
backend/pytest.ini                           # markers: integration, e2e, live (testpaths unchanged)
frontend/package.json                        # @playwright/test, allure-playwright, scripts: test:e2e, test:e2e:ui, report
.github/workflows/ci-cd.yaml                 # additive, opt-in jobs only
```

### 4.3 Explicitly untouched

`backend/app/**`, `frontend/src/**`, `infrastructure/k8s/**`, Keycloak realm/clients, `docker-compose.yml`,
`frontend/Dockerfile`, existing tests, existing CI jobs and their `needs` graph.

---

## 5. Test inventory (ID convention)

Existing tests are **mapped** into the sprint matrix (not duplicated); new tests fill gaps only.

### Sprint 1 — Authentication, accounts, organizations

| ID range | Category | Layer | Validates |
|---|---|---|---|
| `AUTH-001…010` | Functional / E2E | Playwright | guard redirect for anonymous users, Keycloak sign-in, dashboard render, role badge vs `/auth/me`, logout ends SSO, `NONE` read-only, `/settings/org` and `/platform` forbidden by role, no access token in `localStorage`, public invite preview |
| `ORG-001…012` | API / Integration | pytest (`tests_integration`) + Postman | invitation create (ORG_ADMIN) / 403 (DEVELOPER) / 400 foreign `repository_ids`, list w/o token leakage, accept happy path + repo grants, invalid token, expired token, double accept, org settings GET/PUT + 403, non-member uniform 404, `/auth/me` role+capabilities ×6 identities |
| `SEC-001…005` | Security | ZAP baseline + pytest | passive baseline report, 401 without bearer, forged/unsigned token, expired token, security headers |

### Sprint 2 — GitHub integration, webhook and worker

| ID range | Category | Layer | Validates |
|---|---|---|---|
| `WEBHOOK-001…012` | Unit / Contract | pytest | valid signature accepted, invalid → 401, missing signature → 401, missing event header, malformed JSON, non-PR event skipped, unsupported action skipped, unwatched repo `ignored`, duplicate delivery skipped, installation event provisions org, `installation_repositories` sync, missing installation id |
| `WORKER-001…010` | Integration | pytest + real Redis/BullMQ | enqueue on webhook, consume → `processing` → `completed`, PR file fetch with installation token (stubbed HTTP), diff chunking, failure → `failed` + error, retry re-queues, idempotency, job status endpoint, `staged` vs `auto` posting |
| `GITHUB-001…004` | End-to-end | Playwright (+ documented manual) | install URL from UI, repository listing, PR list → PR detail navigation, review status visibility |

### Sprint 3 — Static analysis and AI review

| ID range | Category | Layer | Validates |
|---|---|---|---|
| `ANALYSIS-001…008` | Static analysis | real semgrep-service + real SonarQube | semgrep detects benchmark defects, semgrep normalization, Sonar analysis of benchmark repo, Sonar normalization, merge/`also_detected_by`, severity mapping, engine-failure isolation, snippet enrichment |
| `REVIEW-001…012` | Backend / AI | pytest (deterministic LLM fixtures) | findings routing into specialists, parallel orchestration, partial failure, invalid JSON handling, timeout, orchestrator dedupe/strongest severity/statistics, scan-report endpoint, validate/resolve/dismiss/restore, summary edit + staged post, LLM settings CRUD, unified report generation |
| `REVIEW-E2E-001…005` | Complete review E2E | Playwright | review detail + severity labels, finding qualification persists after reload, staged post → posted state, scan-report 404 → "no enrichment", partial-review banner |

### Sprint 4 — Administration and configuration

| ID range | Category | Layer | Validates |
|---|---|---|---|
| `ADMIN-001…008` | Functional / E2E | Playwright | platform overview users/orgs + pagination (real API), org settings update + persistence after reload, posting-mode change, read-only banner, unauthorized `/settings/org`. Console sub-pages are **mockup-only** → documented, **not** tested |
| `AUTHZ-001…010` | Authorization / Integration | pytest (`tests_integration`) | platform read bypass, F2 carve-outs (no bypass on post/dismiss/validate/summary), cross-org 404, repo visibility scoping, 422 validation, platform ceilings, `/users` restricted, tenant hook best-effort, persistence read-back, 403 vs 404 uniformity |
| `PERF-001…005` | Performance | k6 | smoke (1 VU), load (10 VU), stress (ramp), authenticated endpoints, thresholds + error-rate report |

---

## 6. Failure policy

* Application logic is **never** changed to make a test pass.
* A new test that exposes a real defect is recorded in `TEST_PLAN.md` as
  `FAILED — defect observed (not fixed, out of scope)` with the exact reproduction command, and reported in the final report.
* A test that cannot run is recorded as `BLOCKED` with the exact missing service/variable and the command to run once available.
* No fabricated results, screenshots, or coverage numbers. Baseline numbers come from real executions only.

---

## 7. CI/CD integration (additive only)

New jobs, all **independent** (nothing in the existing `build-images → trivy → push → update-manifests → argocd` chain
is modified, nothing `needs` the new jobs):

| Job | Trigger | Notes |
|---|---|---|
| `api-contract` | every push/PR | boots uvicorn against the service Postgres/Redis, runs the Keycloak-free subset of the Postman collection with Newman, uploads the HTML report |
| `e2e-playwright` | `workflow_dispatch` only | needs a reachable Keycloak + SPA origin (`E2E_BASE_URL`); skipped with an explicit message when absent |
| `security-baseline` | `workflow_dispatch` only | ZAP baseline against a containerised backend on the runner, uploads HTML+JSON |
| `perf-smoke` | `workflow_dispatch` only | k6 smoke only (never load/stress), uploads summary JSON |

All jobs `upload-artifact` their reports; secrets are only ever read through `env:` from GitHub secrets.

---

## 8. Execution phases

| # | Phase | Exit criterion |
|---|---|---|
| 1 | Foundation: `.gitignore`, `requirements-test.txt`, Docker pg/redis, **existing 508 backend + 563 frontend tests unchanged and green**, coverage + pytest-html generated | baseline reports exist |
| 2 | E2E stack: `bootstrap_env.py` → `codesage_e2e` → `seed_e2e_db.py` → `start_e2e_stack.sh`; `/api/v1/health` and `/api/v1/auth/me` verified with a real token | disposable backend answers on :8002 |
| 3 | Backend suites: Sprint 2 → 1 → 3 → 4 contract/integration tests + Allure results + `tests_integration` | ID-labelled results in Allure |
| 4 | Playwright: config → auth setup → POMs → 4 sprint specs | `npx playwright show-report` renders all specs |
| 5 | Aux tools: Newman, ZAP (+ asset checks), k6, Sonar benchmark (kept), Semgrep live | reports in `testing/reports/` |
| 6 | CI jobs (additive) | workflow lint-clean, existing jobs untouched |
| 7 | Docs + full run + final report | `SCREENSHOT_GUIDE.md` matches real artifacts |

### Completion record (2026-10-31)

Phases 1–7 are implemented and executed. The disposable API was freshly rebuilt,
its dedicated database was reset/migrated through revision 023, and the
deterministic fixtures were reloaded. `/api/v1/health` returned successfully on
127.0.0.1:8002. The outcome table and artifact paths are in
[`TEST_PLAN.md`](TEST_PLAN.md).

The executed gates include 522 backend tests passed (6 skipped), 563 frontend
specs passed, 11 real-Keycloak integration checks, 10 Playwright checks, Newman
3/3, live Semgrep, a retained SonarQube benchmark, and k6 smoke (10,805 checks,
0 failures). Type-check, lint, production build/static asset checks, shell
syntax, Python compilation, and workflow/collection metadata validation passed.
The ZAP baseline had 0 failures and 3 warnings; the warnings are listed in
`TEST_PLAN.md` as observed defects, with application logic left untouched.
Screenshots remain a presentation step: use the commands and captions in
[`SCREENSHOT_GUIDE.md`](SCREENSHOT_GUIDE.md) to capture the real reports into
the PFE report workspace.

---

## 9. The twelve screenshots

| # | Sprint | Category | Report |
|---|---|---|---|
| 1 | S1 | Functional/E2E | Playwright HTML (`AUTH-*`) |
| 2 | S1 | API/Integration | pytest-html / Allure (`ORG-*`) |
| 3 | S1 | Security | ZAP HTML baseline |
| 4 | S2 | Unit/Contract | pytest-html (`WEBHOOK-*`) |
| 5 | S2 | Integration | Allure (`WORKER-*`) |
| 6 | S2 | E2E | Playwright HTML (`GITHUB-*`) |
| 7 | S3 | Static analysis | SonarQube dashboard of the **kept** benchmark project |
| 8 | S3 | Static analysis | Semgrep live run + findings JSON |
| 9 | S3 | Full review E2E | Allure / Playwright (`REVIEW-E2E-*`) |
| 10 | S4 | Functional/E2E | Playwright HTML (`ADMIN-*`) |
| 11 | S4 | Authorization | Allure (`AUTHZ-*`) |
| 12 | S4 | Performance | k6 summary output |

---

## 10. Final user workflow

```bash
# Step 1 — start services
./scripts/testing/start_e2e_stack.sh          # Docker pg/redis + disposable backend :8002
./scripts/testing/allure-up.sh                # Allure Docker Service :5050

# Step 2 — one command per sprint (or `all`)
./scripts/testing/run-sprint.sh 1

# Step 3 — open reports
./scripts/testing/allure-open.sh              # http://127.0.0.1:5050/allure-docker-service/latest-report
cd frontend && npx playwright show-report     # Playwright HTML
xdg-open ../testing/reports/pytest-html/index.html

# Step 4 — capture the 12 screenshots
#   docs/testing/SCREENSHOT_GUIDE.md

# Step 5 — paste screenshots + French captions into the PFE report
```
