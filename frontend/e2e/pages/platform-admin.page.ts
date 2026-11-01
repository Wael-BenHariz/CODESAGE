import type { Page } from '@playwright/test';
export class PlatformAdminPage {
  constructor(private readonly page: Page) {}
  async open(): Promise<void> {
    await this.page.goto('/platform');
  }
}
