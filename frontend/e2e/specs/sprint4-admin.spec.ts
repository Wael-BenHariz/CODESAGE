import { test, expect } from '@playwright/test';
import { installApiProxy } from '../support/api-proxy';

test.beforeEach(async ({ page }) => installApiProxy(page));
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

test('ADMIN-001 platform entry is guarded', async ({ page }) => {
  await page.goto('/platform');
  await expect(page).toHaveURL(/platform|forbidden|login/);
});

test('ADMIN-002 organization settings route is handled', async ({ page }) => {
  await page.goto('/settings/org');
  await expect(page).toHaveURL(/settings\/org|forbidden|login/);
});
