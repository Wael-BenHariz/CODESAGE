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
   * (SUPER_ADMIN | DEVELOPER | GUEST). Optional because legacy cached
   * profiles may not carry it yet.
   */
  role?: string;
}
