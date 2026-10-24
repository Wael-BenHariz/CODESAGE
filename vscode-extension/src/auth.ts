import type { SecretStorage } from 'vscode';
import type { AuthProvider } from './types';

export const DEV_TOKEN_KEY = 'codesage.devToken';

export class DevTokenAuthProvider implements AuthProvider {
  readonly kind = 'dev' as const;

  constructor(private readonly secrets: SecretStorage) {}

  async hasToken(): Promise<boolean> {
    return Boolean(await this.secrets.get(DEV_TOKEN_KEY));
  }

  async getHeaders(): Promise<Record<string, string>> {
    const token = await this.secrets.get(DEV_TOKEN_KEY);
    if (!token) {
      throw new Error(
        'Missing CodeSage development token. Run "CodeSage: Set Development Token" first.'
      );
    }
    return { 'X-CodeSage-Dev-Token': token };
  }

  describe(): string {
    return 'Development token (no user or organization context)';
  }

  async setToken(token: string): Promise<void> {
    await this.secrets.store(DEV_TOKEN_KEY, token);
  }

  async clearToken(): Promise<void> {
    await this.secrets.delete(DEV_TOKEN_KEY);
  }
}
