import type { Page } from '@playwright/test';
export class InviteAcceptPage {
  constructor(private readonly page: Page) {}
  async open(token: string): Promise<void> {
    await this.page.goto(`/invite/accept?token=${encodeURIComponent(token)}`);
  }
}
