import { PlatformUser, PlatformUserList, User, CapabilityFlags } from '../../models/user.model';
import { PaginatedResponse } from '../../models/pagination.model';

/**
 * Users/auth mapping layer — the ONE place snake_case user payloads become
 * the camelCase models components render (Step 0 constraint #3).
 *
 * Wire shape: `UserResponse` / `UserListResponse` in
 * `backend/app/schemas/user.py`, returned by `GET /auth/me`,
 * `GET|PATCH /users/me`, `GET /users`, `GET /users/{user_id}`.
 * Every field is optional at the DTO level so a partial or older payload
 * degrades to empty values instead of throwing.
 */

/** Raw permission flags as the wire sends them (`capability_flags()`). */
export interface RawCapabilityFlags {
  view?: boolean;
  trigger?: boolean;
  request?: boolean;
  review?: boolean;
  repo_config?: boolean;
  repo_admin?: boolean;
  platform?: boolean;
}

export interface UserResponseDto {
  id: string;
  keycloak_id?: string | null;
  role?: string | null;
  github_id?: number | null;
  login: string;
  email?: string | null;
  name?: string | null;
  avatar_url?: string | null;
  created_at?: string;
  updated_at?: string;
  /** Top-level `capabilities` of `GET /auth/me` (flags of the global role). */
  capabilities?: RawCapabilityFlags;
  /** Workspace contexts of `GET /auth/me` (effective role + flags each). */
  workspaces?: Array<{
    id: string;
    type: 'PERSONAL' | 'ORG';
    name: string;
    role: 'ORG_ADMIN' | 'REVIEWER' | 'DEVELOPER' | 'NONE';
    github_account_login?: string | null;
    /** Per-workspace permission flags — rendered, never re-derived. */
    capabilities?: RawCapabilityFlags;
  }>;
}

export type UserListResponseDto = PaginatedResponse<UserResponseDto>;

/**
 * Convert the wire's snake_case flags to the camelCase model view.
 *
 * Missing flags (legacy cached payload) fail closed to read-only: `view`
 * is true because every membership — NONE included — may read; every
 * mutation flag defaults to false until the server says otherwise.
 */
export function mapCapabilityFlags(raw: RawCapabilityFlags | undefined): CapabilityFlags {
  return {
    view: raw?.view ?? true,
    trigger: raw?.trigger ?? false,
    request: raw?.request ?? false,
    review: raw?.review ?? false,
    repoConfig: raw?.repo_config ?? false,
    repoAdmin: raw?.repo_admin ?? false,
    platform: raw?.platform ?? false
  };
}

/** Profile view used by the session (AuthService) — tolerant of nulls. */
export function toUser(dto: UserResponseDto): User {
  const baseUser: User = {
    id: dto.id,
    login: dto.login,
    email: dto.email ?? '',
    name: dto.name ?? null,
    // `avatar_url` can be null — an empty string keeps <img [src]> valid.
    avatarUrl: dto.avatar_url ?? '',
    createdAt: dto.created_at ?? '',
    updatedAt: dto.updated_at ?? '',
    role: dto.role ?? undefined
  };

  if (dto.capabilities) {
    baseUser.capabilities = mapCapabilityFlags(dto.capabilities);
  }

  if (dto.workspaces) {
    // Server flags are authoritative — no client-side role derivation.
    baseUser.workspaces = dto.workspaces.map(ws => ({
      id: ws.id,
      type: ws.type,
      name: ws.name,
      role: ws.role,
      isPersonal: ws.type === 'PERSONAL',
      githubAccountLogin: ws.github_account_login ?? null,
      capabilities: mapCapabilityFlags(ws.capabilities)
    }));
  }

  return baseUser;
}

/** Admin user table row (PLATFORM_ADMIN). */
export function toPlatformUser(dto: UserResponseDto): PlatformUser {
  return {
    id: dto.id,
    keycloakId: dto.keycloak_id ?? null,
    role: dto.role ?? 'NONE',
    githubId: dto.github_id ?? null,
    login: dto.login,
    email: dto.email ?? null,
    name: dto.name ?? null,
    avatarUrl: dto.avatar_url ?? null,
    createdAt: dto.created_at ?? '',
    updatedAt: dto.updated_at ?? ''
  };
}

export function toPlatformUserList(dto: UserListResponseDto): PlatformUserList {
  return {
    items: (dto.items ?? []).map(toPlatformUser),
    total: dto.total ?? 0,
    page: dto.page ?? 1,
    perPage: dto.per_page ?? 0,
    pages: dto.pages ?? 0
  };
}
