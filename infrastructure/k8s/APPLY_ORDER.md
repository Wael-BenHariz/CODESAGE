# CodeSage — Kubernetes Apply Order

Run everything from the repository root.

## Step 1 — MetalLB install (manual, once):

```bash
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.5/config/manifests/metallb-native.yaml
kubectl wait --namespace metallb-system --for=condition=ready pod --selector=app=metallb --timeout=90s
kubectl apply -k infrastructure/k8s/base/metallb/
```

> **Note:** k3s ships with Klipper ServiceLB. If MetalLB and ServiceLB fight
> over LoadBalancer IPs, edit `/etc/systemd/system/k3s.service` → add
> `--disable servicelb` to `ExecStart`, then `sudo systemctl daemon-reload &&
> sudo systemctl restart k3s`.

## Step 2 — ingress-nginx install (manual, once):

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/baremetal/deploy.yaml
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=90s
kubectl apply -k infrastructure/k8s/base/ingress/ingress-nginx-patch.yaml
```

## Step 3 — Namespace:

```bash
kubectl apply -f infrastructure/k8s/base/namespace.yaml
```

## Step 3b — Istio service mesh (before any workloads are created):

> Installs istiod only (`profile: minimal`) — **no gateways**;
> ingress-nginx remains the cluster's single router. The namespace label
> MUST land before the workloads in Steps 4–11 are created, otherwise they
> come up without sidecars and the mesh policies below don't cover them.
> Retrofitting on a live cluster: label the namespace, then
> `kubectl -n codesage rollout restart deployment --all` (brief restart of
> every workload; Keycloak is `Recreate` — auth is down during its restart).

```bash
# istioctl — never curl|sh. Either:
#   sudo pacman -S istio                # system-wide (needs sudo)
# or user-local (same package, no sudo): ~/.local/bin/istioctl
istioctl install -f infrastructure/k8s/istio/istio-operator.yaml -y
kubectl label namespace codesage istio-injection=enabled
kubectl apply -k infrastructure/k8s/istio/
istioctl analyze -n codesage           # must report no issues
```

> What this deploys (modelled on faas `k8s/07-istio`): `PeerAuthentication`
> **PERMISSIVE** (plaintext ingress keeps working), two
> `RequestAuthentication`s (both Keycloak issuer shapes → `requestPrincipals`),
> a namespace deny-floor `AuthorizationPolicy` plus per-workload allows —
> backend = explicit public paths + JWT required, repo-tenant = actuator +
> in-mesh callers, frontend/keycloak/semgrep = allow-all (public by design),
> postgres = pod-CIDR plaintext, redis = in-mesh mTLS identity only —
> namespace-wide CORS (`OPTIONS`) + sidecar-metrics (`:15090`) allowances,
> and `service-entry.yml` registering GitHub OAuth2/App API egress
> (`github.com`, `api.github.com`). The worker has no inbound listener and
> is covered by the deny floor.

## Step 4 — PostgreSQL:

```bash
kubectl apply -k infrastructure/k8s/base/postgres/
kubectl wait --namespace codesage --for=condition=ready pod --selector=app=postgres --timeout=120s
```

## Step 5 — DB migrations (one-time):

> **Requires the backend image to be imported first** (Step 7 builds it) —
> either run Step 7 before this step, or run migrations from a machine with
> the repo checked out: `DATABASE_URL=... alembic upgrade head`.

```bash
kubectl run alembic-migrate --rm -it --restart=Never \
  --namespace=codesage \
  --image=codesage-backend:latest \
  --overrides='{"spec":{"imagePullPolicy":"Never"}}' \
  --env-from=secret/codesage-backend-secret \
  -- alembic upgrade head
```

## Step 6 — Redis:

```bash
kubectl apply -k infrastructure/k8s/base/redis/
```

## Step 7 — Build and import images:

```bash
bash infrastructure/k8s/scripts/build-and-deploy.sh
```

> Uses `nerdctl` (builds straight into k3s containerd) when available,
> otherwise `docker build` + `k3s ctr images import`.

## Step 7b — semgrep-service (before backend — owns ConfigMap `semgrep-config`):

> The backend and worker deployments `envFrom` ConfigMap `semgrep-config`,
> which lives in `base/semgrep-service/` — applying the backend first leaves
> its pods stuck in `CreateContainerConfigError`. Requires the image from
> Step 7 (`127.0.0.1:5000/codesage/semgrep-service:$TAG`, `IfNotPresent`).

```bash
kubectl apply -k infrastructure/k8s/base/semgrep-service/
kubectl wait --namespace=codesage --for=condition=ready pod --selector=app=semgrep-service --timeout=120s
kubectl -n codesage port-forward svc/semgrep-service 18080:8080 &  # optional
curl localhost:18080/readyz   # {"status":"ready","rules":"/opt/semgrep-rules"}
```

See `docs/SEMGREP.md` (smoke test, troubleshooting).

## Step 8 — Backend + worker:

```bash
kubectl apply -k infrastructure/k8s/base/backend/
```

## Step 8b — repo-tenant-service (one enabled repo = one namespace):

```bash
# First deploy only:
#   cp infrastructure/k8s/base/repo-tenant-service/secret.example.yaml \
#      infrastructure/k8s/base/repo-tenant-service/secret.yaml
# Fill INTERNAL_SERVICE_TOKEN — it MUST equal REPO_TENANT_INTERNAL_TOKEN in
# base/backend/secret.yaml (X-Service-Token auth between the two services).
kubectl apply -k infrastructure/k8s/base/repo-tenant-service/
kubectl wait --namespace codesage --for=condition=ready pod --selector=app=repo-tenant-service --timeout=120s
```

> The backend calls it in-cluster at
> `http://repo-tenant-service.codesage.svc.cluster.local:8085`. Those calls
> are **best-effort** (3 s timeout, failures logged): saving watched-repos
> never fails because this service is down. The ingress exposes its
> read-only API under `/api/v1/repos` (Keycloak JWT); its
> `/api/v1/repos/internal/*` endpoints are X-Service-Token only.
> Quota defaults live in ConfigMap `repo-tenant-config` (`DEFAULT_*` keys)
> — provisioning proceeds on them whenever a remote source is absent.

## Step 9 — Frontend:

```bash
kubectl apply -k infrastructure/k8s/base/frontend/
```

## Step 10 — Ingress rules:

```bash
kubectl apply -f infrastructure/k8s/base/ingress/ingress.yaml
```

## Step 11 — Get MetalLB IP and update secret:

```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller
# Note the EXTERNAL-IP
# First deploy only: cp infrastructure/k8s/base/backend/secret.example.yaml \
#                     infrastructure/k8s/base/backend/secret.yaml
# Edit secret.yaml: replace METALLB_IP placeholders + fill in real credentials
kubectl apply -k infrastructure/k8s/base/backend/
kubectl rollout restart deployment/codesage-backend -n codesage
```

> **Secret hygiene:** `base/backend/secret.yaml` is **gitignored** — only the
> `secret.example.yaml` template is committed. The filled file holds real
> credentials (GitHub OAuth + App key, Groq/Gemini/SonarQube tokens); never
> `git add -f` it. Values live in `backend/.env` for local dev.
> The same rule applies to `base/repo-tenant-service/secret.yaml`
> (gitignored; committed template is `secret.example.yaml`).

## Post-deploy — SonarQube URL

`SONARQUBE_URL` in the backend secret must be the in-cluster service name
(`http://sonarqube-sonarqube.sonarqube.svc.cluster.local:9000`). Verify with:

```bash
kubectl run curl-check --rm -it --restart=Never --image=curlimages/curl -- \
  curl -s http://sonarqube-sonarqube.sonarqube.svc.cluster.local:9000/api/system/status
```

## Step 12 — Monitoring (Prometheus + Grafana):

```bash
kubectl create namespace monitoring   # deliberately NOT mesh-injected:
                                      # scrapes stay plaintext, which the
                                      # codesage AuthorizationPolicies allow

# --server-side is REQUIRED: dashboards-downloads.yaml contains a 468 KB
# ConfigMap (Node Exporter Full) that exceeds client-side apply's 256 KB
# last-applied-configuration annotation limit.
kubectl apply -k infrastructure/k8s/monitoring/ --server-side

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring -f infrastructure/k8s/monitoring/values.yaml

# postgres-exporter — the password comes from the live backend secret,
# never from the repo:
kubectl -n codesage get secret codesage-backend-secret \
  -o jsonpath='{.data.DATABASE_URL}'    # base64-decode it, take the password
helm upgrade --install postgres-exporter prometheus-community/prometheus-postgres-exporter \
  --namespace monitoring \
  --set config.datasource.host=postgres-service.codesage.svc.cluster.local \
  --set-string config.datasource.port=5432 \
  --set config.datasource.user=codesage \
  --set config.datasource.password=<from DATABASE_URL> \
  --set config.datasource.database=codesage
```

> **Grafana** — no ingress by design, port-forward only:
>
> ```bash
> kubectl -n monitoring port-forward svc/monitoring-grafana 3000:3000
> # http://localhost:3000 — admin / admin  (grafana-admin-secret; CHANGE
> # before any shared use — the secret is committed on purpose, dev only)
> ```
>
> **Dashboards: 37** = 25 kube-prometheus-stack built-ins + 9 vendored
> community dashboards (gnetId/revision pinned in
> `monitoring/dashboards-downloads.yaml`) + 3 authored
> (`CodeSage / Overview (Mesh RED)`, `CodeSage / repo-tenant-service`,
> `Keycloak 24 - JVM & System Metrics`). The vendored 9 are **ConfigMaps
> labeled `grafana_dashboard=1`** — NOT the chart's `dashboards:` gnetId
> block: the bundled grafana chart (13.3.1) renders a single sidecar
> provider only, so the chart's own gnetId downloads land where no provider
> reads (see the header of `dashboards-downloads.yaml`). Editing a
> dashboard via the UI is lost on restart (`allowUiUpdates: false`) — edit
> the JSON in the repo and re-apply.
>
> **Keycloak metrics**: KC 24 serves them at **`/auth/metrics` on :8080**
> with `KC_METRICS_ENABLED=true` (there is no separate management port).
> The scrape job is `keycloak` in `monitoring/prometheus-scrape-secret.yaml`.

## CPU budget — read before adding workloads (4-core node):

The node has **4000m allocatable CPU**; the running stack schedules
**3675m (91%)** — roughly **325m headroom**:

| What                                          | CPU     |
| --------------------------------------------- | ------- |
| CodeSage workloads (7 pods × 250m)            | 1700m   |
| SonarQube                                     | 400m    |
| istiod (trimmed from the 500m default)        | 250m    |
| monitoring stack (trimmed, see below)         | 225m    |
| kube-system + ingress-nginx                   | 300m    |
| `istio-proxy` sidecars (8 × 100m/128Mi)*      | 800m    |
| **Total**                                     | **3675m** |

\* every injected pod carries an `istio-proxy` native sidecar requesting
100m — budget **+100m per new `codesage` workload**.

Trimmed on purpose (defaults do not fit this node):

- istiod 500m → 250m — `istio/istio-operator.yaml` (`values.pilot`)
- prometheus 200 → 150m, grafana 100 → 50m, alertmanager 50 → 25m —
  `monitoring/values.yaml`

Operational consequences:

- **A rolling update of a `codesage` pod needs 350m** (250m app + 100m
  proxy) but only ~325m is free → the surge pod stays `Pending` until
  space is made: scale SonarQube down first
  (`kubectl -n sonarqube scale sts sonarqube --replicas=0` frees 400m),
  roll, then scale it back.
- **Keycloak's deployment strategy is `Recreate`** — any restart takes
  login/token issuance down for its duration. Brief and expected; plan it.
- SonarQube degrades gracefully: an unreachable analyzer only sets
  `sonar_scan_failed` on the review — Semgrep still runs.
- Check the live allocation:
  `kubectl describe node <node> | sed -n '/Allocated resources/,/^Events/p'`

## Post-deploy verification:

```bash
IP=$(kubectl -n ingress-nginx get svc ingress-nginx-controller \
     -o jsonpath='{.status.loadBalancer.ingress[0].ip}')   # app address
B=http://$IP/api/v1

# auth matrix (mesh + app + CORS):
curl -s -o /dev/null -w '%{http_code}\n' $B/health                       # 200 public
curl -s -o /dev/null -w '%{http_code}\n' $B/health/ready                 # 200 public
curl -s -o /dev/null -w '%{http_code}\n' $B/auth/keycloak/config         # 200 public
curl -s -o /dev/null -w '%{http_code}\n' $B/settings/llm                 # 403 mesh deny (no JWT)
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Authorization: Bearer garbage' $B/settings/llm                     # 401 app rejects
curl -s -o /dev/null -w '%{http_code}\n' -X OPTIONS \
  -H "Origin: http://$IP" -H 'Access-Control-Request-Method: PUT' \
  -H 'Access-Control-Request-Headers: authorization,content-type' \
  $B/settings/llm                                                        # 200 CORS preflight

# mesh (all codesage pods: 4 (CDS,LDS,EDS,RDS)):
istioctl proxy-status

# scrape health — expect 0 not-up (targets vary with nodes/instances):
kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090 &
sleep 3
curl -s localhost:9090/api/v1/targets | python3 -c \
  "import json,sys; t=json.load(sys.stdin)['data']['activeTargets'];
   print(len(t),'targets;', sum(1 for x in t if x['health']!='up'), 'not-up')"

# dashboards — expect 37:
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:3000 &
sleep 3
curl -s -u admin:admin 'localhost:3000/api/search?type=dash-db&limit=300' \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)),'dashboards')"
```

> **CORS gotcha**: the pod's allow-list is exactly `CORS_ORIGINS` from
> `base/backend/secret.yaml` (this cluster: `http://10.171.24.201`). Any
> other origin gets `400 Disallowed CORS origin` from FastAPI — correct
> app behavior, not a mesh regression.
