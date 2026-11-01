#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
case "${1:-}" in
  1) export E2E_ROLE="${E2E_ROLE:-ORG_ADMIN}" ;;
  2) export E2E_ROLE="${E2E_ROLE:-DEVELOPER}" ;;
  3) export E2E_ROLE="${E2E_ROLE:-REVIEWER}" ;;
  4|all) export E2E_ROLE="${E2E_ROLE:-PLATFORM_ADMIN}" ;;
esac
source "$ROOT/scripts/testing/e2e-auth.env.sh"
source "$ROOT/scripts/testing/integration-auth.env.sh"
case "${1:-}" in
  1) selection='auth|invitation|org|role|test_s1' ; browser_filter='AUTH|ORG' ;;
  2) selection='webhook|worker|repo_tenant|test_s2' ; browser_filter='GITHUB' ;;
  3) selection='agent|review|scan|test_s3' ; browser_filter='REVIEW' ;;
  4) selection='authorization|platform|test_s4' ; browser_filter='ADMIN|AUTHZ' ;;
  all) selection=''; browser_filter='' ;;
  *) echo 'Usage: run-sprint.sh 1|2|3|4|all' >&2; exit 2 ;;
esac
mkdir -p "$ROOT/testing/reports/allure-results" "$ROOT/testing/reports/pytest-html"
if [[ "$1" == all ]]; then
  "$ROOT/scripts/testing/start_e2e_stack.sh"
  "$ROOT/scripts/testing/allure-up.sh"
  "$ROOT/scripts/testing/run-backend.sh"
  "$ROOT/scripts/testing/run-integration.sh"
  if [[ -n "${E2E_USERNAME:-}" && -n "${E2E_USER_PASSWORD:-}" ]]; then
    "$ROOT/scripts/testing/run-playwright.sh"
  else
    echo 'Skipping Playwright: set E2E_USERNAME and E2E_USER_PASSWORD.'
  fi
  "$ROOT/scripts/testing/run-newman.sh"
  "$ROOT/scripts/testing/zap-baseline.sh"
  "$ROOT/scripts/testing/k6-run.sh" smoke
  "$ROOT/scripts/testing/allure-generate.sh"
else
  cd "$ROOT/backend"
  "$ROOT/scripts/testing/python.sh" -m pytest tests tests_integration -m "not live and not e2e" -k "$selection" \
    --alluredir=../testing/reports/allure-results --html=../testing/reports/pytest-html/sprint-${1}.html --self-contained-html
fi
if [[ "$1" != all ]]; then
  if [[ -n "${E2E_USERNAME:-}" && -n "${E2E_USER_PASSWORD:-}" ]]; then
    "$ROOT/scripts/testing/run-playwright.sh" --grep "$browser_filter"
  else
    echo 'Skipping Playwright: set E2E_USERNAME and E2E_USER_PASSWORD.'
  fi
fi
