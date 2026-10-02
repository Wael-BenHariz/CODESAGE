#!/bin/bash
set -e

# Run from the repository root:
#   bash infrastructure/k8s/scripts/build-and-deploy.sh
#   TAG=v0.3.0 bash infrastructure/k8s/scripts/build-and-deploy.sh
#
# Image strategy (semgrep release, plan section 2.4):
#   - backend / worker / semgrep-service are pinned to
#     127.0.0.1:5000/codesage/<name>:$TAG — never :latest. They are pushed
#     to the local registry AND imported into k3s containerd under the same
#     refs, so the imagePullPolicy: IfNotPresent manifests resolve locally
#     whether or not /etc/rancher/k3s/registries.yaml declares the registry.
#   - frontend / repo-tenant keep their existing :latest conventions.
#
# Image import strategy:
#   - docker daemon reachable -> docker build + `k3s ctr images import`
#   - else, nerdctl present   -> builds directly into k3s containerd
#                                (namespace k8s.io; requires buildkitd)

TAG="${TAG:-v0.2.1-semgrep}"
BACKEND_IMG="127.0.0.1:5000/codesage/backend:${TAG}"
WORKER_IMG="127.0.0.1:5000/codesage/worker:${TAG}"
SEMGREP_IMG="127.0.0.1:5000/codesage/semgrep-service:${TAG}"

TIMESTAMP=$(date +%Y%m%d%H%M%S)
FRONTEND_TAG="codesage-frontend:${TIMESTAMP}"
REPO_TENANT_TAG="codesage-repo-tenant-service:${TIMESTAMP}"

USE_DOCKER=0
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  USE_DOCKER=1
elif command -v nerdctl >/dev/null 2>&1; then
  USE_DOCKER=0
else
  echo "ERROR: neither a reachable docker daemon nor nerdctl found" >&2
  exit 1
fi

if [ "$USE_DOCKER" -eq 0 ]; then
  BUILD_BACKEND=(sudo nerdctl build --namespace k8s.io -t "$BACKEND_IMG" -f backend/Dockerfile ./backend)
  BUILD_WORKER=(sudo nerdctl build --namespace k8s.io -t "$WORKER_IMG" -f backend/Dockerfile.worker ./backend)
  BUILD_SEMGREP=(sudo nerdctl build --namespace k8s.io -t "$SEMGREP_IMG" -f services/semgrep-service/Dockerfile ./services/semgrep-service)
  BUILD_FRONTEND=(sudo nerdctl build --namespace k8s.io -t codesage-frontend:latest -f frontend/Dockerfile ./frontend)
  # Both tags are required: the Deployment runs
  # 127.0.0.1:5000/codesage-repo-tenant-service:latest (pullPolicy Never).
  BUILD_REPO_TENANT=(sudo nerdctl build --namespace k8s.io -t codesage-repo-tenant-service:latest -t 127.0.0.1:5000/codesage-repo-tenant-service:latest -f repo-tenant-service/Dockerfile ./repo-tenant-service)
else
  BUILD_BACKEND=(docker build -t "$BACKEND_IMG" -f backend/Dockerfile ./backend)
  BUILD_WORKER=(docker build -t "$WORKER_IMG" -f backend/Dockerfile.worker ./backend)
  BUILD_SEMGREP=(docker build -t "$SEMGREP_IMG" -f services/semgrep-service/Dockerfile ./services/semgrep-service)
  BUILD_FRONTEND=(docker build -t "$FRONTEND_TAG" -f frontend/Dockerfile ./frontend)
  BUILD_REPO_TENANT=(docker build -t "$REPO_TENANT_TAG" -f repo-tenant-service/Dockerfile ./repo-tenant-service)
fi

echo "=== Building backend image ($BACKEND_IMG) ==="
"${BUILD_BACKEND[@]}"

echo "=== Building worker image ($WORKER_IMG) ==="
"${BUILD_WORKER[@]}"

echo "=== Building semgrep-service image ($SEMGREP_IMG) ==="
"${BUILD_SEMGREP[@]}"

echo "=== Building frontend image ==="
"${BUILD_FRONTEND[@]}"
if [ "$USE_DOCKER" -eq 1 ]; then
  docker tag "$FRONTEND_TAG" codesage-frontend:latest
fi

echo "=== Building repo-tenant-service image ==="
"${BUILD_REPO_TENANT[@]}"
if [ "$USE_DOCKER" -eq 1 ]; then
  docker tag "$REPO_TENANT_TAG" codesage-repo-tenant-service:latest
  # The Deployment runs 127.0.0.1:5000/codesage-repo-tenant-service:latest
  # (pullPolicy Never) — keep that ref fresh on every build too.
  docker tag "$REPO_TENANT_TAG" 127.0.0.1:5000/codesage-repo-tenant-service:latest
fi

if [ "$USE_DOCKER" -eq 1 ]; then
  echo "=== Pushing release images to the local registry ==="
  # registry:2 container serving 127.0.0.1:5000 (start it if it exists
  # but is stopped). A failed push is only a warning: the containerd
  # import below is what the IfNotPresent manifests rely on.
  if docker ps -a --format '{{.Names}}' | grep -qx local-registry; then
    docker start local-registry >/dev/null || true
  fi
  for img in "$BACKEND_IMG" "$WORKER_IMG" "$SEMGREP_IMG"; do
    if ! docker push "$img"; then
      echo "WARNING: push of $img failed (continuing — import below)" >&2
    fi
  done

  echo "=== Importing images into k3s ==="
  if [ -f /etc/rancher/k3s/registries.yaml ]; then
    # registries.yaml declares 127.0.0.1:5000 as a plain-HTTP registry, so
    # kubelet pulls the pinned images from the local registry directly and
    # the containerd import is unnecessary (sudo-free runs).
    echo "registries.yaml found - skipping import (kubelet pulls from the registry)"
  else
    docker save "$BACKEND_IMG" "$WORKER_IMG" "$SEMGREP_IMG" | sudo k3s ctr images import -
    docker save codesage-frontend:latest | sudo k3s ctr images import -
    docker save codesage-repo-tenant-service:latest 127.0.0.1:5000/codesage-repo-tenant-service:latest | sudo k3s ctr images import -
  fi
fi

echo "=== Applying manifests ==="
# Releases must not touch the data tier: base also carries the one-shot
# keycloak-db-init Job (psql against postgres) for FIRST-TIME cluster
# bootstrap. It is TTL-deleted after completion, so a plain `apply -k`
# would recreate it — and re-run SQL — on every release. Render the base
# and drop that one Job here; bootstrap it explicitly once instead:
#   kubectl apply -f infrastructure/k8s/base/keycloak/keycloak-db-init.yaml
kubectl kustomize infrastructure/k8s/base/ \
  | awk 'BEGIN{RS="\n---\n"} !($0 ~ /kind: Job/ && $0 ~ /name: keycloak-db-init/){ if (n++) printf "\n---\n"; printf "%s", $0 }' \
  | kubectl apply -f -

echo "=== Rolling out deployments ==="
kubectl rollout restart deployment/codesage-backend -n codesage
kubectl rollout restart deployment/codesage-worker -n codesage
kubectl rollout restart deployment/semgrep-service -n codesage
kubectl rollout restart deployment/codesage-frontend -n codesage
kubectl rollout restart deployment/repo-tenant-service -n codesage

echo "=== Waiting for rollout ==="
kubectl rollout status deployment/codesage-backend -n codesage
kubectl rollout status deployment/codesage-worker -n codesage
kubectl rollout status deployment/semgrep-service -n codesage
kubectl rollout status deployment/codesage-frontend -n codesage
kubectl rollout status deployment/repo-tenant-service -n codesage

echo "=== Done ==="
kubectl get pods -n codesage
