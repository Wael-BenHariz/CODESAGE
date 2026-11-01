import type { Page } from '@playwright/test';

export async function installApiProxy(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async route => {
    const requestUrl = new URL(route.request().url());
    const backend = new URL(process.env.E2E_API_PROXY_URL || 'http://127.0.0.1:8002');
    backend.pathname = requestUrl.pathname;
    backend.search = requestUrl.search;
    try {
      const response = await route.fetch({ url: backend.toString() });
      await route.fulfill({ response });
    } catch {
      // Route teardown can race an in-flight SPA request. Keep Playwright's
      // error output from serializing authorization headers or token values.
      await route.fulfill({ status: 502, body: '' }).catch(() => undefined);
    }
  });
}
