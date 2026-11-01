#!/usr/bin/env bash
set -euo pipefail
curl --fail --silent --show-error -o /dev/null -X GET http://127.0.0.1:5050/allure-docker-service/generate-report
echo 'Allure report generated: http://127.0.0.1:5050/allure-docker-service/projects/default/reports/latest/index.html'
