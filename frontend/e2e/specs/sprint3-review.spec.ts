import { test, expect } from '@playwright/test';
import { installApiProxy } from '../support/api-proxy';

test.beforeEach(async ({ page }) => installApiProxy(page));
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

test('REVIEW-E2E-001 reviews screen renders', async ({ page }) => {
  await page.goto('/reviews');
  await expect(page.locator('body')).not.toBeEmpty();
});

test('REVIEW-E2E-002 review detail route is handled', async ({ page }) => {
  await page.goto('/reviews/00000000-0000-4000-8000-000000000002');
  await expect(page.locator('body')).not.toBeEmpty();
});
