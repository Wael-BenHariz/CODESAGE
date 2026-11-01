#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/scripts/testing/integration-auth.env.sh"
mkdir -p "$ROOT/testing/reports/pytest-html" "$ROOT/testing/reports/allure-results"
cd "$ROOT/backend"
"$ROOT/scripts/testing/python.sh" -m pytest tests_integration -m integration "$@" \
  --html=../testing/reports/pytest-html/integration.html --self-contained-html \
  --alluredir=../testing/reports/allure-results
