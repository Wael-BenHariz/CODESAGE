# Testing infrastructure

This directory documents the repeatable test stack described in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). The disposable dependency
containers bind only to loopback. They use `codesage_test` for the existing
pytest suite and `codesage_e2e` for the disposable API, with Redis databases
15 and 14 respectively.

## Local backend setup

Run `scripts/testing/start-test-deps.sh` to start isolated Postgres and Redis
containers. It refuses to claim ports 5432 or 6379 if another service already
owns them. Install test-only dependencies with
`pip install -r backend/requirements.txt -r backend/requirements-test.txt`,
then run `scripts/testing/run-backend.sh`. HTML, coverage, and Allure raw
results are written under `testing/reports/`. `scripts/testing/start-test-deps.sh
--down` removes only the two named CodeSage testing containers.

## Disposable API

`scripts/testing/python.sh scripts/testing/bootstrap_env.py` creates a mode 0600
`backend/.env.e2e` from the checked-in placeholder template (never your local
backend secrets), replacing secrets used
by the API and pinning database/Redis to the loopback test containers. The
file is ignored by Git. `scripts/testing/python.sh scripts/testing/seed_e2e_db.py` resets and migrates only
`codesage_e2e`, then inserts fixed-UUID organization/member fixtures.
`scripts/testing/start_e2e_stack.sh` builds the E2E-only backend image and
starts it with host networking, bound to 127.0.0.1:8002 by default (override
with `E2E_API_PORT` when needed). It converts dotenv quoting to Docker env-file
syntax through a private temporary file. Stop the API and containers with
`scripts/testing/stop_e2e_stack.sh`.

## Browser tests

Install frontend dependencies with `cd frontend && npm ci`, then configure the
ignored E2E identity file and `backend/.env.e2e` as described above. Run
`scripts/testing/run-playwright.sh` (or set `E2E_BASE_URL`, `E2E_USERNAME`,
and `E2E_USER_PASSWORD` before invoking `npm run test:e2e` directly); the HTML report is written to
`frontend/playwright-report/`. Authentication state is private and ignored by
Git. `frontend/e2e/support/api-proxy.ts` forwards `/api/v1/**` requests from
the browser specs to the disposable API at 127.0.0.1:8002. The auth setup removes the SPA's GitHub IdP
hint only for the test login, then uses the Keycloak realm's native user form.

Real-service integration tests are opt-in. Set `KEYCLOAK_PUBLIC_URL`,
`E2E_API_URL`, and `E2E_USERS_JSON` (a JSON object keyed by `platform`,
`org_admin`, `reviewer`, `developer`, `none`, and `invitee`, each with
`username` and `password`) in the process environment. Do not put that JSON in
the repository or attach it to reports. Then run
`scripts/testing/run-integration.sh`.

## Auxiliary tools

`scripts/testing/run-newman.sh` runs the Postman smoke collection. ZAP and k6
wrappers enforce a loopback HTTP target. SonarQube benchmark projects are
retained and their key is recorded in `testing/reports/sonar-project-key.txt`;
deletion requires the exact project key and typed confirmation. Allure
requires Docker and uses loopback port 5050. Executed outcomes and report
locations are recorded in [TEST_PLAN.md](TEST_PLAN.md).

## Safety

Do not place credentials in reports or commit local environment files. Live
integration, security, and performance commands are documented as they are
implemented; they must target only the disposable local API unless explicitly
designated as a live analysis-service benchmark.
