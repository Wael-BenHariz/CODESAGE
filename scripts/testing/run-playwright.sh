#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/scripts/testing/e2e-auth.env.sh"
export E2E_API_PROXY_URL="${E2E_API_PROXY_URL:-http://127.0.0.1:${E2E_API_PORT:-8002}}"
cd "$ROOT/frontend"
npx playwright test "$@"
