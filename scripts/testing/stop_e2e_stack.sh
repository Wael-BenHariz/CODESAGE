#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if docker inspect codesage-e2e-api >/dev/null 2>&1; then
  owner="$(docker inspect -f '{{ index .Config.Labels "codesage.testing" }}' codesage-e2e-api)"
  [[ "$owner" == true ]] || { echo 'Refusing to remove an unrelated codesage-e2e-api container.' >&2; exit 1; }
  docker rm -f codesage-e2e-api >/dev/null
fi
scripts/testing/start-test-deps.sh --down
