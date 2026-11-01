import { test, expect } from '@playwright/test';
import { installApiProxy } from '../support/api-proxy';

test.beforeEach(async ({ page }) => installApiProxy(page));
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

test('GITHUB-001 repositories route renders', async ({ page }) => {
  await page.goto('/repositories');
  await expect(page.locator('body')).not.toBeEmpty();
});

test('GITHUB-002 PR route handles a repository path', async ({ page }) => {
  await page.goto('/repositories/codesage/example/pulls');
  await expect(page.locator('body')).not.toBeEmpty();
});
