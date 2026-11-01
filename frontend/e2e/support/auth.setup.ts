import { test as setup, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { installApiProxy } from './api-proxy';

const authDir = path.join(__dirname, '../.auth');
setup('authenticate through Keycloak password form', async ({ page, baseURL }) => {
  const username = process.env.E2E_USERNAME;
  const password = process.env.E2E_USER_PASSWORD;
  if (!username || !password)
    throw new Error('Set E2E_USERNAME and E2E_USER_PASSWORD in the shell environment');
  fs.mkdirSync(authDir, { recursive: true, mode: 0o700 });
  await installApiProxy(page);
  await page.route('**/auth/realms/**/protocol/openid-connect/auth**', async route => {
    const authorizationUrl = new URL(route.request().url());
    authorizationUrl.searchParams.delete('kc_idp_hint');
    await route.continue({ url: authorizationUrl.toString() });
  });
  await page.goto(baseURL!);
  await page.getByRole('link', { name: /sign in/i }).click();
  await page.getByRole('button', { name: /continue with github/i }).click();
  await expect(page).toHaveURL(/protocol\/openid-connect\/auth/);
  await page.getByLabel(/username/i).fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: /sign in|log in/i }).click();
  await expect(page).not.toHaveURL(/protocol\/openid-connect\/auth/);
  await page.context().storageState({ path: path.join(authDir, 'e2e-user.json') });
});
