import type { Page } from '@playwright/test';
export class DashboardPage {
  constructor(private readonly page: Page) {}
  async open(): Promise<void> {
    await this.page.goto('/dashboard');
  }
}
