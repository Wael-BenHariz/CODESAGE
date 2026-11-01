#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$ROOT/testing/reports/newman"
exec npx --yes --package newman --package newman-reporter-htmlextra newman run "$ROOT/testing/postman/CodeSage.postman_collection.json" \
  -e "$ROOT/testing/postman/codesage-local.postman_environment.json" \
  --reporters cli,htmlextra --reporter-htmlextra-export "$ROOT/testing/reports/newman/index.html" "$@"
