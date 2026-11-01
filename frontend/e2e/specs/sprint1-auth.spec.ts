import { test, expect } from '@playwright/test';
import { installApiProxy } from '../support/api-proxy';

test.beforeEach(async ({ page }) => installApiProxy(page));
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

test('AUTH-001 public login screen renders', async ({ page }) => {
  await page.goto('/login');
  await expect(page.locator('body')).not.toBeEmpty();
});

test('AUTH-002 anonymous access to dashboard redirects to login', async ({ browser }) => {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  try {
    await installApiProxy(page);
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/login|auth|forbidden/);
  } finally {
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await context.close();
  }
});

test('AUTH-003 public help renders', async ({ page }) => {
  await page.goto('/help');
  await expect(page.locator('body')).not.toBeEmpty();
});
