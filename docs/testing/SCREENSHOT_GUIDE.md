# Screenshot guide

Capture only real report pages after the corresponding command completes.
Keep screenshots in the PFE report workspace, not in generated report folders.

| # | Sprint / evidence | Generate | Capture |
|---|---|---|---|
| 1 | S1 Playwright auth | `cd frontend && npm run test:e2e -- --grep AUTH` | Playwright HTML report with AUTH cases |
| 2 | S1 org/API | `cd backend && pytest tests_integration/test_s1_invitations_orgs.py --html=../testing/reports/pytest-html/org.html --self-contained-html` | pytest HTML result table |
| 3 | S1 security | `scripts/testing/zap-baseline.sh` | `testing/reports/zap/baseline.html` summary |
| 4 | S2 webhook | `cd backend && pytest tests/test_contract_webhooks.py --html=../testing/reports/pytest-html/webhooks.html --self-contained-html` | pytest result table |
| 5 | S2 worker | `cd backend && pytest tests_integration/test_s2_worker_queue.py` | generated Allure latest report |
| 6 | S2 GitHub UI | `cd frontend && npm run test:e2e -- --grep GITHUB` | Playwright HTML result |
| 7 | S3 Sonar | `scripts/testing/sonar-benchmark.sh` | retained benchmark project's SonarQube dashboard |
| 8 | S3 Semgrep | `pytest backend/tests/e2e/test_static_analysis_live.py -v` | live findings JSON/report |
| 9 | S3 review UI | `cd frontend && npm run test:e2e -- --grep REVIEW-E2E` | Playwright/Allure report |
| 10 | S4 admin | `cd frontend && npm run test:e2e -- --grep ADMIN` | Playwright HTML result |
| 11 | S4 authorization | `pytest backend/tests_integration/test_s4_authorization_matrix.py -v` | Allure authorization result |
| 12 | S4 performance | `scripts/testing/k6-run.sh smoke` | k6 terminal summary and summary JSON |

Use captions that state the command, environment, and observed outcome. Do not
present a planned or skipped run as a passing result.
