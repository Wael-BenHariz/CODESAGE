import type { Page } from '@playwright/test';
export class LoginPage {
  constructor(private readonly page: Page) {}
  async open(): Promise<void> {
    await this.page.goto('/login');
  }
  async login(username: string, password: string): Promise<void> {
    await this.page.getByRole('button', { name: /login|sign in/i }).click();
    await this.page.getByLabel(/username/i).fill(username);
    await this.page.getByLabel(/password/i).fill(password);
    await this.page.getByRole('button', { name: /sign in|log in/i }).click();
  }
}
