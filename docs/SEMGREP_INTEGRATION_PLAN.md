# Semgrep Integration Plan

Branch: `feat/semgrep-integration` · Complements SonarQube, does not replace it.

## 1. Recon — how the current scan pipeline works

All paths are relative to the repo root. Line numbers are best-effort anchors.

### (a) How a scan is triggered, and by whom

```
GitHub webhook  POST /api/v1/webhooks/github        (backend/app/api/routes/webhooks.py)
  -> queue_review(...)  BullMQ queue `review-requests` on Redis
  -> worker app/workers/main.py (BullMQ worker, BULLMQ_CONCURRENCY)
  -> app/workers/review_processor.py::process_review_job()
```

- The **worker** owns the whole review pipeline (`review_processor.py:111`): load rows →
  idempotency guard → `processing` → fetch diff → static analysis → agents → post GitHub
  review → `completed`.
- The backend/API never scans anything; it only enqueues and serves results.

### (b) How the code to scan reaches SonarQube

Worker-side, **stateless, no shared volume, no git clone, no repo-tenant-service involvement**:

1. `github_service.get_pull_request_files(owner, repo, pr_number, installation_id)` —
   paginated PR file list with patches (installation token).
2. For every reviewable file, `github_app.fetch_file_content(...)` pulls the **full file
   contents at `pr.head_sha`** from the GitHub Contents API
   (`review_processor.py:219-239` → `sonar_files: [{"filename", "content"}]`).
3. `sonarqube_service.scan(project_key, files, language)`
   (`backend/app/services/sonarqube.py:367`):
   - creates a throwaway SonarQube project `codesage-review-<review[:8]>` (Community
     Edition = one branch per project),
   - `write_files_to_temp_dir()` dumps the contents into a
     `tempfile.TemporaryDirectory()` preserving relative paths (path-traversal guarded),
   - runs `sonar-scanner` via `asyncio.create_subprocess_exec` **inside the worker
     container** (image already ships sonar-scanner + JRE),
   - polls `/api/ce/activity`, fetches `/api/issues/search`, then **always deletes the
     project** in `finally`.

### (c) How SonarQube results are fetched and stored

- `get_issues()` returns `list[SonarIssue]` (dataclass: `key, rule, severity, type,
  component, line, message, effort, tags`; `component` already stripped of the
  `projectKey:` prefix) — `sonarqube.py:270`.
- `group_issues_by_agent()` buckets them into the 5 specialist domains
  (`security, complexity, performance, test_coverage, style`) — first matching
  predicate wins (`sonarqube.py:322`).
- **Findings are never persisted.** They live in worker memory for the duration of the
  job. Only the *final agent output* is stored: `reviews` (summary, severity,
  `github_review_id`) and `review_comments` (per-comment file/line/severity/category).
  Scan failures are appended to `reviews.error_message`.

### (d) How agents receive findings

- `ReviewOrchestrator.run(context, sonar_groups)`
  (`backend/app/services/review_orchestrator.py:29`) runs the 5 specialists in parallel
  (semaphore=1 to respect Groq free-tier quotas) with `return_exceptions=True`.
- Each agent gets `context.with_issues(sonar_groups.get(domain, []))` →
  `ReviewContext.sonar_issues: list[SonarIssue]` (`agents/schemas.py:17`).
- `_SonarSpecialistAgent._build_prompt` renders them via `format_sonar_issues()` as a
  compact Markdown block ("SonarQube has already analyzed…") — the diff stays in the
  context for reference (`specialist_agents.py:37-79`).
- Output contract `AgentResult{agent, confidence, comments[]}` →
  `OrchestratorAgent.synthesize()` → `ReviewResult` (posted to GitHub verbatim).

## 2. Design

### 2.1 How the Semgrep service gets the source code

**Decision: the worker uploads a `tar.gz` of the same fetched workspace to
`POST /scan` (stateless upload — per the preferred option).**

Why this beats the alternatives:

| Option | Verdict |
|---|---|
| **Worker uploads tar.gz (chosen)** | Reuses the exact `sonar_files` already fetched for SonarQube → both tools scan *identical input at the same ref*, which is what makes cross-tool dedup meaningful. No GitHub credentials in the new service, no PVC, no ordering/lifetime coupling, request-scoped temp dirs are trivial to garbage-collect. |
| Semgrep service git-clones the repo | Needs GitHub tokens inside a second service, doubles GitHub API/rate exposure, and scans HEAD instead of the PR's `head_sha` (divergent input → weaker dedup). |
| Shared PVC between worker and service | Couples pod lifetimes, needs RWX volume plumbing on a single-node cluster, and leaves stale checkouts behind. |
| Run semgrep inside the worker image | Rejected by requirement #4 (standalone always-on Deployment). |

The tar.gz is built from the worker's temp workspace (already path-traversal-checked on
write), keeping the upload small (only PR-changed files, not the whole repo).

### 2.2 Component map

```
worker (review_processor)
   |-- sonar_files: [{"filename","content"}]          (existing, GitHub API @ head_sha)
   |        |                     |
   |        |                     +--> tar.gz --> POST semgrep-service /scan  (SEMGREP_* env)
   |        v
   |   sonarqube_service.scan()  (existing, in-worker sonar-scanner)
   |        |                              |
   v        v                              v
   normalize_sonar(...)             normalize_semgrep(...)      [normalizers/]
             \                        /
              +--> merge + dedup ----+   -> ScanReport (NormalizedFinding list)
                                          |-- persisted: scan_reports table (migration 010)
                                          |-- API: GET /reviews/{id}/scan-report?tool=&severity=
                                          v
                                   ReviewContext.findings (agents' input)
                                          v
                                   5 specialists -> synthesis (output contract unchanged)
```

- **`services/semgrep-service/`** (new, repo root — mirrors `repo-tenant-service/` layout
  conventions: own app, Dockerfile, tests, `.dockerignore`): FastAPI, `GET /healthz`,
  `GET /readyz`, `POST /scan` (multipart). Runs
  `semgrep scan --json --metrics=off --disable-version-check --config /opt/semgrep-rules`
  via `asyncio.create_subprocess_exec`. OSS rules baked into the image at build time.
- **`backend/app/services/normalizers/`** (new package): `schema.py`
  (`NormalizedFinding`, `ScanReport`), `sonarqube.py`, `semgrep.py`, `merge.py`.
- **`backend/app/services/semgrep.py`**: `SemgrepClient` (httpx async, retries/backoff,
  `SEMGREP_SERVICE_URL`).
- **Persistence**: new `scan_reports` table (migration `010`) — JSONB `findings` +
  `tools_run`/`tools_failed`/`summary`, FK to `reviews`. Sonar's existing behaviour
  (memory-only) keeps working through the same code path; the report is written once
  per completed scan, best-effort (a report insert failure must never fail a review).
- **API**: `GET /api/v1/reviews/{review_id}/scan-report` (authenticated like the other
  review endpoints) with `tool` and `severity` query filters. Existing endpoints/fields
  untouched → frontend backward compatible.
- **k8s**: kustomize base at `infrastructure/k8s/base/` (the brief's `k8s/` path =
  this directory). New `base/semgrep-service/` (Deployment + Service, ClusterIP only —
  **no Ingress**). **No NetworkPolicy** — the cluster defines none today (rule: only add
  if the cluster already uses them); adding the first one risks breaking traffic.

### 2.3 Config env vars

| Env | Default | Meaning |
|---|---|---|
| `SEMGREP_ENABLED` | `true` | Master switch (worker skips Semgrep when false) |
| `SEMGREP_SERVICE_URL` | `http://semgrep-service:8080` (in-cluster same-ns) | Service base URL |
| `SEMGREP_TIMEOUT_SECONDS` | `60` | Client-side timeout for one `/scan` call |
| `SEMGREP_MAX_UPLOAD_BYTES` | `5242880` (5 MiB) | Request size limit enforced by the service |
| `MAX_CONCURRENT_SCANS` | `2` | Service-side semaphore |
| `SONAR_TIMEOUT_SECONDS` | — | **Covered by the existing `SONARQUBE_ANALYSIS_TIMEOUT` (default 120)** — it already bounds scanner run + CE polling; adding a second knob for one behaviour would create ambiguity. Documented as the sonar timeout. |

### 2.4 Image & tag policy

- `TAG=v0.2.0-semgrep` everywhere (build, push, manifests) — never `:latest`.
- `127.0.0.1:5000/codesage/semgrep-service:$TAG`
- `127.0.0.1:5000/codesage/backend:$TAG` (existing `backend/Dockerfile`)
- `127.0.0.1:5000/codesage/worker:$TAG` (existing `backend/Dockerfile.worker`)
- `imagePullPolicy: IfNotPresent` on all three.

Known environment facts (recon, 2026-10-02):
- The `local-registry` docker container exists but was **Exited (255)** — Step 8 must
  `docker start local-registry` before pushing.
- Current backend/worker Deployments use `codesage-backend:latest` + `imagePullPolicy:
  Never` (images imported into k3s containerd by hand). Moving to registry tags with
  `IfNotPresent` requires either (a) `/etc/rancher/k3s/registries.yaml` declaring
  `127.0.0.1:5000` as a plain-HTTP registry for kubelet pulls, or (b) pre-importing the
  tagged images into containerd (same refs) so `IfNotPresent` finds them locally. (a)
  needs root → exact commands will be printed for the user, never edited silently.

## 3. Steps → deliverables (one Conventional Commit each)

| Step | Commit | Deliverables |
|---|---|---|
| 0 | `docs: add semgrep integration plan` | this file |
| 1 | `feat: add unified finding schema` | `normalizers/schema.py` (`NormalizedFinding`, `ScanReport`), migration `010_scan_reports`, model + export, unit tests |
| 2 | `refactor: normalize sonarqube findings` | `normalizers/sonarqube.py::normalize_sonar`, fixture tests, no behaviour regression |
| 3 | `feat(semgrep-service): add standalone scan service` | `services/semgrep-service/` (FastAPI, hardened extractor, semaphore, Dockerfile w/ baked OSS rules, tests, `.dockerignore`) |
| 4 | `feat: add semgrep client and normalizer` | `services/semgrep.py` client + `normalizers/semgrep.py`, fixture tests |
| 5 | `feat: run sonarqube and semgrep in parallel` | worker pipeline `gather`, partial-failure tolerance, `normalizers/merge.py` (dedup + `also_detected_by`), persistence, API endpoint + filters, tests |
| 6 | `feat: feed unified findings to review agents` | `ReviewContext.findings`, updated prompts (two analyzers, validate/prioritize/chunk), snippet enrichment ±10 lines, mocked-LLM tests |
| 7 | `feat(k8s): add semgrep-service deployment` | `base/semgrep-service/`, env on backend/worker, tag updates, `kubectl apply --dry-run=server` |
| 8 | `chore: release $TAG images and manifests` | build/push 3 images, verify registry catalog + manifest tags, rollout |
| 9 | `test: add e2e scan test and smoke script` | connectivity, port-forward scan, full E2E (parallel timing evidence), failure-mode test, `scripts/smoke_semgrep.sh` |
| 10 | `docs: document semgrep integration` | architecture (mermaid), env vars, rebuild/deploy, rule updates, troubleshooting |

## 4. Hard constraints carried into every step

- One commit per step; tests/linters green before each; no secrets/.env committed.
- Semgrep OSS only: no account, no token, `--metrics=off` always; rules baked at build.
- A failed/timed-out Semgrep (or SonarQube) scan must **never** fail the review —
  matches the existing "SonarQube failure ⇒ empty groups" contract (brief A7.3).
- Agent output contract (`AgentResult`/`ReviewResult`) stays unchanged → no frontend
  change required.
- Existing SonarQube behaviour remains the fallback path when `SEMGREP_ENABLED=false`.
