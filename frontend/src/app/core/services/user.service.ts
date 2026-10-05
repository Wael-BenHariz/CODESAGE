import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { ApiService } from './api.service';
import { PlatformUser, PlatformUserList } from '../models/user.model';
import {
  UserListResponseDto,
  UserResponseDto,
  toPlatformUser,
  toPlatformUserList
} from './mappers/user.mapper';

/**
 * `/users/*` route group (backend `app/api/routes/users.py`).
 *
 * The list/detail routes are PLATFORM_ADMIN-only reads; there is no
 * cross-user update endpoint (see docs/BACKEND_GAPS_FOR_UI.md §2), so this
 * service exposes reads only. `GET|PATCH|DELETE /users/me` stay in
 * `AuthService` (session profile).
 */
@Injectable({ providedIn: 'root' })
export class UserService {
  private readonly api = inject(ApiService);

  /** `GET /users` — PLATFORM_ADMIN user table (paginated). */
  listUsers(page = 1, perPage = 20): Observable<PlatformUserList> {
    return this.api
      .get<UserListResponseDto>('/users', { page, per_page: perPage })
      .pipe(map(toPlatformUserList));
  }

  /** `GET /users/{user_id}` — PLATFORM_ADMIN single-user read. */
  getUser(userId: string): Observable<PlatformUser> {
    return this.api.get<UserResponseDto>(`/users/${userId}`).pipe(map(toPlatformUser));
  }
}
