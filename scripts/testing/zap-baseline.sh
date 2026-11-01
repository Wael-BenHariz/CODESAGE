#!/usr/bin/env bash
set -euo pipefail
target="${ZAP_TARGET:-http://127.0.0.1:${E2E_API_PORT:-8002}}"
[[ "$target" =~ ^http://(127\.0\.0\.1|localhost):[0-9]{1,5}(/[^?#]*)?$ ]] || { echo 'ZAP target must be a loopback HTTP URL with an explicit port' >&2; exit 2; }
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$ROOT/testing/reports/zap"
docker run --rm --network host -v "$ROOT/testing/reports/zap:/zap/wrk/:rw" zaproxy/zap-stable \
  zap-baseline.py -t "$target" -m 2 -r baseline.html -J baseline.json -I
