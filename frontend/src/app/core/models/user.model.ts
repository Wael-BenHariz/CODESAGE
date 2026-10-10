/**
 * Permission flags as `GET /auth/me` reports them (backend
 * `capability_flags()`) — the frontend renders from these instead of
 * re-deriving role lists, so a matrix change lands in exactly one place
 * (the backend).
 *
 * The mapper (`core/services/mappers/user.mapper.ts`) converts the
 * snake_case wire keys (`repo_config` / `repo_admin`) to this camelCase
 * view.
 */
export interface CapabilityFlags {
  view: boolean;
  trigger: boolean;
  request: boolean;
  review: boolean;
  repoConfig: boolean;
  repoAdmin: boolean;
  platform: boolean;
}

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
  /**
   * Permission flags for the *global* realm role (top-level
   * `capabilities` of `GET /auth/me`). Optional so a cached legacy
   * profile degrades to role-based fallbacks.
   */
  capabilities?: CapabilityFlags;
}

/** One user as the PLATFORM_ADMIN user routes (`GET /users`,
 * `GET /users/{user_id}`) present them — camelCase view of
 * `UserResponse` (backend `app/schemas/user.py`), built by
 * `core/services/mappers/user.mapper.ts`. */
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
