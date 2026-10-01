# repo-tenant-service

Spring Boot 4 (Java 21) microservice implementing CodeSage's **one enabled repo =
one Kubernetes namespace = one tenant** rule.

When a user enables a repository in CodeSage (the `watched_repos` review
switch), the backend fires a best-effort call to this service, which creates the
tenant's namespace plus its quota objects. Disabling tears everything down.

```
user toggles repo  ─▶  FastAPI backend  ──POST /api/v1/repos/internal/enable──▶  repo-tenant-service
                       (watched_repos)        X-Service-Token, fire-and-forget        │
                                                                                      ▼
                                                                            namespace + ResourceQuota
                                                                            (per-repo tenant)
```

The backend call is **best-effort**: 3 s timeout, failures are logged and
swallowed — saving watched-repos never fails because this service (or any other
dependency) is down.

## API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/v1/repos/internal/enable` | `X-Service-Token` | Upsert tenant + ensure namespace exists (idempotent) |
| `POST` | `/api/v1/repos/internal/disable` | `X-Service-Token` | Full teardown: delete namespace **then** tenant row (idempotent; `status: ABSENT` for unknown repos) |
| `GET`  | `/api/v1/repos/internal/namespaces` | `X-Service-Token` | List `ENABLED` tenants (namespace, fullName) |
| `GET`  | `/api/v1/repos` | Keycloak JWT | List tenants |
| `GET`  | `/api/v1/repos/{id}` | Keycloak JWT | Tenant detail |
| `GET`  | `/api/v1/repos/{id}/status` | Keycloak JWT | Status + provisioning status |

Payloads are camelCase (Spring's default naming strategy).

**Disable semantics**: the row is deleted only after the namespace delete call
succeeds — a failing cluster can never leak an orphaned namespace (the row stays
so the delete can be retried by disabling again).

## Configuration

All settings are env vars (k8s ConfigMap `repo-tenant-config` +
Secret `repo-tenant-service-secret`; see
`infrastructure/k8s/base/repo-tenant-service/`).

| Variable | Default | Notes |
|----------|---------|-------|
| `SERVER_PORT` | `8085` | |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USERNAME` / `DB_PASSWORD` | — | Shared `codesage` Postgres. Schema is owned by the backend's **Alembic migration 009** (`repo_tenants`); `JPA_DDL_AUTO=none` — Hibernate never alters tables |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | — | Cache only; a lenient `CacheErrorHandler` means Redis down = no cache, never a failed request |
| `JWT_JWK_SET_URI` / `KEYCLOAK_ALLOWED_ISSUERS` | — | RS256 tokens, multi-issuer allow-list (external MetalLB address + in-cluster service DNS) |
| `INTERNAL_SERVICE_TOKEN` | `dev-token` | Must equal the backend's `REPO_TENANT_INTERNAL_TOKEN` |
| `QUOTA_SERVICE_URL` | *(empty)* | Optional remote quota source. Empty ⇒ **no network call**; any URL set ⇒ failures fall back to the defaults below |
| `DEFAULT_MAX_CPU`, `DEFAULT_MAX_MEMORY`, `DEFAULT_MAX_TOTAL_CPU`, `DEFAULT_MAX_TOTAL_MEMORY`, `DEFAULT_MAX_FUNCTIONS`, `DEFAULT_MAX_PODS` | `500m`, `512Mi`, `10`, `20Gi`, `10`, `50` | Safe defaults injected via the ConfigMap — enabling a repo never blocks on another microservice |

## RBAC

The service account `repo-tenant-service` gets a least-privilege ClusterRole:
`namespaces` `get/list/watch/create/delete` and
`resourcequotas`/`limitranges` `get/list/watch/create/update/patch/delete`
(`infrastructure/k8s/base/repo-tenant-service/rbac.yaml`).

## Local development

There is no Java/Maven on the host — run the build in Docker:

```bash
# tests (28 tests)
docker run --rm -v "$PWD":/workspace -v faas-m2:/root/.m2 \
  -w /workspace/repo-tenant-service maven:3.9.6-eclipse-temurin-21 mvn test -B

# image (multi-stage: builds the jar inside — no mvn package needed on host)
docker build -t codesage-repo-tenant-service:latest \
  -f repo-tenant-service/Dockerfile ./repo-tenant-service

# run against local Postgres/Redis
docker run --rm -p 8085:8085 \
  --add-host=host.docker.internal:host-gateway \
  -e DB_HOST=host.docker.internal -e DB_NAME=codesage \
  -e DB_USERNAME=codesage -e DB_PASSWORD=codesage \
  -e REDIS_HOST=host.docker.internal -e REDIS_PASSWORD=redis_password \
  codesage-repo-tenant-service:latest
curl localhost:8085/actuator/health   # {"status":"UP"}
```

## Deploy

See `infrastructure/k8s/APPLY_ORDER.md` **Step 8b** — first deploy copies
`secret.example.yaml` → `secret.yaml` (gitignored) and the image is built,
imported and rolled out by `infrastructure/k8s/scripts/build-and-deploy.sh`.
The ingress exposes the read API under `/api/v1/repos` (before the generic
`/api` rule).
