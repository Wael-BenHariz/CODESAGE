import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.E2E_BASE_URL || 'http://10.171.24.201';

export default defineConfig({
  testDir: './e2e/specs',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['allure-playwright', { resultsDir: '../testing/reports/allure-results' }],
    ['list']
  ],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome']
  },
  projects: [
    { name: 'auth-setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      dependencies: ['auth-setup'],
      testMatch: /.*\.spec\.ts/,
      use: { storageState: './e2e/.auth/e2e-user.json' }
    }
  ]
});
