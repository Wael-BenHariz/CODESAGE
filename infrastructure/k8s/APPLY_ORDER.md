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

## Step 8 — Backend + worker:

```bash
kubectl apply -k infrastructure/k8s/base/backend/
```

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

## Post-deploy — SonarQube URL

`SONARQUBE_URL` in the backend secret must be the in-cluster service name
(`http://sonarqube-sonarqube.sonarqube.svc.cluster.local:9000`). Verify with:

```bash
kubectl run curl-check --rm -it --restart=Never --image=curlimages/curl -- \
  curl -s http://sonarqube-sonarqube.sonarqube.svc.cluster.local:9000/api/system/status
```
