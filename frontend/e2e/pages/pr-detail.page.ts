import type { Page } from '@playwright/test';
export class PullRequestDetailPage {
  constructor(private readonly page: Page) {}
  async open(id: string): Promise<void> {
    await this.page.goto(`/pull-requests/${id}`);
  }
}
