#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/frontend"
npm run build
dist="$(find dist -type f -name index.html -print -quit)"
test -n "$dist"
base="$(dirname "$dist")"
! rg -n 'bypassSecurityTrust|innerHTML\s*=' src
test -s "$dist"
rg -q '<app-root' "$dist"
echo "Static asset checks passed for $base"
