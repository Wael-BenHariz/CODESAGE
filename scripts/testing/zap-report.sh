#!/usr/bin/env bash
set -euo pipefail
test -s testing/reports/zap/baseline.html
printf '%s\n' "$PWD/testing/reports/zap/baseline.html"
