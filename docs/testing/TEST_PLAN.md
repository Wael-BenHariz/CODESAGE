# Test plan and execution record

The full inventory and intended coverage are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
The IDs below are the traceability groups used by the scripts; execution status
must be recorded from actual reports after a run. No result is pre-marked as
passing or failed.

| Sprint | Test IDs | Layer / command | Current status |
|---|---|---|---|
| 1 | AUTH / ORG / SEC | Playwright, `tests_integration`, ZAP | Browser and real identity/org checks passed; ZAP completed with 3 warnings recorded below |
| 2 | WEBHOOK / WORKER / GITHUB | backend tests, integration suite, Playwright | Webhook contracts, worker configuration, and browser route checks passed |
| 3 | ANALYSIS / REVIEW | live Semgrep, SonarQube benchmark, backend tests, Playwright | Live Semgrep and retained Sonar benchmark passed; browser review routes passed |
| 4 | ADMIN / AUTHZ / PERF | integration suite, Playwright, k6 | Authorization checks, browser guards, and k6 smoke passed |

## Executed results (2026-10-31)

| Command / artifact | Result |
|---|---|
| `scripts/testing/run-backend.sh` | 522 passed, 6 skipped; 81% coverage. HTML: `testing/reports/pytest-html/index.html`; coverage: `testing/reports/coverage/` |
| `scripts/testing/run-integration.sh -v` | 11 passed using all six real Keycloak test identities. HTML: `testing/reports/pytest-html/integration.html` |
| `scripts/testing/run-playwright.sh` | 10 passed. HTML: `frontend/playwright-report/`; Allure raw results: `testing/reports/allure-results/` |
| `scripts/testing/run-newman.sh` | 3 requests and 3 assertions passed. HTML: `testing/reports/newman/index.html` |
| `scripts/testing/zap-baseline.sh` | 0 failures, 3 warnings, 65 passive rules passed. Report: `testing/reports/zap/baseline.html` |
| `scripts/testing/k6-run.sh smoke` | 1 VU, 30 seconds, 10,805 checks passed, 0 failed requests; p95 5.62 ms. JSON: `testing/reports/k6/smoke-summary.json` |
| Live Semgrep fixture test | 1 passed against the configured service; `testing/reports/pytest-html/semgrep-live.html` |
| `scripts/testing/sonar-benchmark.sh` | Analysis uploaded successfully. Retained project key is in `testing/reports/sonar-project-key.txt` |
| `npm run test:ci` | 563 passed; frontend coverage: 88.98% lines |
| `npm run type-check`, `npm run lint`, production build/static asset checks | Passed |

### Observed ZAP warnings

`scripts/testing/zap-baseline.sh` reported these findings on the local API:

- `10021`: `X-Content-Type-Options` missing.
- `10049`: response content can be stored/cached, including `robots.txt` and `sitemap.xml` 404 responses.
- `90004`: `Cross-Origin-Resource-Policy` missing or invalid.

These are recorded as `FAILED — defect observed (not fixed, out of testing-only scope)` in keeping with the plan's failure policy. Raw evidence is in `testing/reports/zap/baseline.json`; application code was not changed.

## Test case mapping

Existing unit coverage remains authoritative for application behaviors already
tested in `backend/tests/` and `frontend/src/**/*.spec.ts`. Added contracts are
`WEBHOOK-001..004` in `test_contract_webhooks.py`, worker configuration checks
in `test_worker_lifecycle.py`, and parser failure checks in
`test_agent_failure_modes.py`. Real Keycloak checks are opt-in through
`E2E_USERS_JSON`; live analysis checks require explicit service URLs. The
browser suite uses `E2E_BASE_URL` and isolated `E2E_USERNAME` credentials.

When a run exposes a defect, preserve the exact command and report path here;
do not change application code as part of this testing-only deliverable.
