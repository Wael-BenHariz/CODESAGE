#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/backend"
mkdir -p ../testing/reports/pytest-html ../testing/reports/coverage
"$ROOT/scripts/testing/python.sh" -m pytest tests "$@" --cov=app --cov-report=term-missing --cov-report=html:../testing/reports/coverage --html=../testing/reports/pytest-html/index.html --self-contained-html --alluredir=../testing/reports/allure-results
