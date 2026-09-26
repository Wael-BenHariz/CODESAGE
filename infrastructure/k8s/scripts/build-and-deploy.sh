#!/bin/bash
set -e

# Run from the repository root:
#   bash infrastructure/k8s/scripts/build-and-deploy.sh
#
# Image import strategy:
#   - docker daemon reachable -> docker build + `k3s ctr images import`
#   - else, nerdctl present   -> builds directly into k3s containerd
#                                (namespace k8s.io; requires buildkitd)

TIMESTAMP=$(date +%Y%m%d%H%M%S)
BACKEND_TAG="codesage-backend:${TIMESTAMP}"
WORKER_TAG="codesage-worker:${TIMESTAMP}"
FRONTEND_TAG="codesage-frontend:${TIMESTAMP}"

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
  BUILD_BACKEND=(sudo nerdctl build --namespace k8s.io -t codesage-backend:latest -f backend/Dockerfile ./backend)
  BUILD_WORKER=(sudo nerdctl build --namespace k8s.io -t codesage-worker:latest -f backend/Dockerfile.worker ./backend)
  BUILD_FRONTEND=(sudo nerdctl build --namespace k8s.io -t codesage-frontend:latest -f frontend/Dockerfile ./frontend)
else
  BUILD_BACKEND=(docker build -t "$BACKEND_TAG" -f backend/Dockerfile ./backend)
  BUILD_WORKER=(docker build -t "$WORKER_TAG" -f backend/Dockerfile.worker ./backend)
  BUILD_FRONTEND=(docker build -t "$FRONTEND_TAG" -f frontend/Dockerfile ./frontend)
fi

echo "=== Building backend image ==="
"${BUILD_BACKEND[@]}"
if [ "$USE_DOCKER" -eq 1 ]; then
  docker tag "$BACKEND_TAG" codesage-backend:latest
fi

echo "=== Building worker image ==="
"${BUILD_WORKER[@]}"
# NOTE: do NOT retag the worker image as codesage-backend:latest — the API
# deployment runs that image's default CMD (uvicorn). The worker deployment
# sets its command explicitly and can use either image.
if [ "$USE_DOCKER" -eq 1 ]; then
  docker tag "$WORKER_TAG" codesage-worker:latest
fi

echo "=== Building frontend image ==="
"${BUILD_FRONTEND[@]}"
if [ "$USE_DOCKER" -eq 1 ]; then
  docker tag "$FRONTEND_TAG" codesage-frontend:latest
fi

if [ "$USE_DOCKER" -eq 1 ]; then
  echo "=== Importing images into k3s ==="
  docker save codesage-backend:latest | sudo k3s ctr images import -
  docker save codesage-worker:latest | sudo k3s ctr images import -
  docker save codesage-frontend:latest | sudo k3s ctr images import -
fi

echo "=== Rolling out deployments ==="
kubectl rollout restart deployment/codesage-backend -n codesage
kubectl rollout restart deployment/codesage-worker -n codesage
kubectl rollout restart deployment/codesage-frontend -n codesage

echo "=== Waiting for rollout ==="
kubectl rollout status deployment/codesage-backend -n codesage
kubectl rollout status deployment/codesage-worker -n codesage
kubectl rollout status deployment/codesage-frontend -n codesage

echo "=== Done ==="
kubectl get pods -n codesage
