#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$ROOT/testing/reports/allure-results" "$ROOT/testing/reports/allure"
if docker inspect -f '{{.State.Running}}' codesage-allure 2>/dev/null | grep -qx true; then
  echo 'Allure service already running on 127.0.0.1:5050'
  exit 0
fi
if docker inspect codesage-allure >/dev/null 2>&1; then
  owner="$(docker inspect -f '{{ index .Config.Labels "codesage.testing" }}' codesage-allure)"
  [[ "$owner" == true ]] || { echo 'Refusing to replace an unrelated codesage-allure container.' >&2; exit 1; }
  docker rm codesage-allure >/dev/null
fi
docker run -d --name codesage-allure --label codesage.testing=true -p 127.0.0.1:5050:5050 \
  --user "$(id -u):$(id -g)" \
  -v "$ROOT/testing/reports/allure-results:/app/allure-results" \
  -v "$ROOT/testing/reports/allure:/app/default-reports" \
  -e CHECK_RESULTS_EVERY_SECONDS=NONE frankescobar/allure-docker-service >/dev/null
