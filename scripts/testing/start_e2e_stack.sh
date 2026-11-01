#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
api_port="${E2E_API_PORT:-8002}"
api_url="http://127.0.0.1:${api_port}"
if docker inspect codesage-e2e-api >/dev/null 2>&1; then
  owner="$(docker inspect -f '{{ index .Config.Labels "codesage.testing" }}' codesage-e2e-api)"
  [[ "$owner" == true ]] || { echo 'Refusing to replace an unrelated codesage-e2e-api container.' >&2; exit 1; }
  if [[ "$(docker inspect -f '{{.State.Running}}' codesage-e2e-api)" == true ]] \
    && curl -fsS "$api_url/api/v1/health" >/dev/null 2>&1; then
    echo "E2E backend already running on :${api_port}"
    exit 0
  fi
  docker rm -f codesage-e2e-api >/dev/null
fi
scripts/testing/start-test-deps.sh
scripts/testing/python.sh scripts/testing/bootstrap_env.py
scripts/testing/python.sh scripts/testing/seed_e2e_db.py
docker build -f scripts/testing/Dockerfile.e2e -t codesage-e2e-api:local backend
docker_env_file="$(mktemp)"
trap 'rm -f "$docker_env_file"' EXIT
scripts/testing/python.sh scripts/testing/docker_env_file.py backend/.env.e2e "$docker_env_file"
docker run -d --name codesage-e2e-api --label codesage.testing=true --network host \
  --env-file "$docker_env_file" -e "PORT=${api_port}" codesage-e2e-api:local >/dev/null
for _ in $(seq 1 60); do
  if [[ "$(docker inspect -f '{{.State.Running}}' codesage-e2e-api 2>/dev/null || true)" != true ]]; then
    break
  fi
  if curl -fsS "$api_url/api/v1/health" >/dev/null 2>&1; then
    echo "E2E backend ready on :${api_port}"
    exit 0
  fi
  sleep 1
done
docker logs codesage-e2e-api >&2 || true
echo "E2E backend failed to start on :${api_port}" >&2
exit 1
