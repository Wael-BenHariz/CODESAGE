import { PlatformUser, PlatformUserList, User } from '../../models/user.model';
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
}

export type UserListResponseDto = PaginatedResponse<UserResponseDto>;

/** Profile view used by the session (AuthService) — tolerant of nulls. */
export function toUser(dto: UserResponseDto): User {
  return {
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
