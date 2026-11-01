import type { Page } from '@playwright/test';
export class OrgSettingsPage {
  constructor(private readonly page: Page) {}
  async open(): Promise<void> {
    await this.page.goto('/settings/org');
  }
}
