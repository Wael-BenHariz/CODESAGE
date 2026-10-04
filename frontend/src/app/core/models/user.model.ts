export interface User {
  id: string;
  login: string;
  email: string;
  name: string | null;
  avatarUrl: string;
  createdAt: string;
  updatedAt: string;
  /**
   * Effective app role derived from the Keycloak JWT on every request
   * (PLATFORM_ADMIN | ORG_ADMIN | REVIEWER | DEVELOPER | NONE). Optional
   * because legacy cached profiles may not carry it yet.
   */
  role?: string;
}
