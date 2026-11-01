#!/usr/bin/env bash
set -euo pipefail
scenario="${1:-smoke}"
case "$scenario" in smoke|load|stress) ;; *) echo 'Usage: k6-run.sh smoke|load|stress' >&2; exit 2;; esac
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
target="${K6_BASE_URL:-http://127.0.0.1:${E2E_API_PORT:-8002}}"
[[ "$target" =~ ^http://(127\.0\.0\.1|localhost):[0-9]{1,5}(/[^?#]*)?$ ]] || { echo 'k6 target must be a loopback HTTP URL with an explicit port' >&2; exit 2; }
mkdir -p "$ROOT/testing/reports/k6"
docker run --rm --network host --user "$(id -u):$(id -g)" -v "$ROOT/testing/k6:/scripts:ro" \
  -v "$ROOT/testing/reports/k6:/reports" -e BASE_URL="$target" \
  -e K6_ACCESS_TOKEN="${K6_ACCESS_TOKEN:-}" grafana/k6 run \
  --summary-export="/reports/$scenario-summary.json" "/scripts/$scenario.js"
