#!/usr/bin/env bash
set -euo pipefail
: "${SONARQUBE_URL:?Set SONARQUBE_URL}"
: "${SONARQUBE_TOKEN:?Set SONARQUBE_TOKEN}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$ROOT/testing/reports"
key="codesage-benchmark-$(cat /proc/sys/kernel/random/uuid)"
docker run --rm --network host -v "$ROOT/backend/tests/benchmark_repo:/usr/src" \
  -e SONAR_HOST_URL="$SONARQUBE_URL" -e SONAR_TOKEN="$SONARQUBE_TOKEN" \
  sonarsource/sonar-scanner-cli -Dsonar.projectKey="$key" -Dsonar.sources=.
printf '%s\n' "$key" > "$ROOT/testing/reports/sonar-project-key.txt"
printf 'Created SonarQube benchmark project %s (kept for screenshots)\n' "$key"
