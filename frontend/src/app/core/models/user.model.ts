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

/**
 * One user as the PLATFORM_ADMIN user routes (`GET /users`,
 * `GET /users/{user_id}`) present them — camelCase view of
 * `UserResponse` (backend `app/schemas/user.py`), built by
 * `core/services/mappers/user.mapper.ts`.
 */
export interface PlatformUser {
  id: string;
  keycloakId: string | null;
  /** Realm role vocabulary; unknown/legacy values pass through as-is. */
  role: string;
  githubId: number | null;
  login: string;
  email: string | null;
  name: string | null;
  avatarUrl: string | null;
  createdAt: string;
  updatedAt: string;
}

/** `GET /users` envelope (UserListResponse). */
export interface PlatformUserList {
  items: PlatformUser[];
  total: number;
  page: number;
  perPage: number;
  pages: number;
}
