import { Injectable, inject } from '@angular/core';
import { Observable, map, of, switchMap } from 'rxjs';

import { ApiService } from './api.service';
import { Repository, RepositoryDetail } from '../models/repository.model';
import { GitHubRepo } from '../models/github-app.model';
import {
  RepositoryDto,
  RepositoryDetailDto,
  RepositoryListDto,
  toRepository,
  toRepositoryDetail,
  toRepositoryList
} from './mappers/repository.mapper';

/**
 * Deterministic "definitely does not exist" UUID — used when the owner/name
 * lookup finds nothing. Asking the backend for a record under this id yields
 * its genuine 404, which flows through the ErrorInterceptor (rule 5:
 * 404 → generic not-found page) instead of a synthesized client-side error.
 */
const NIL_UUID = '00000000-0000-0000-0000-000000000000';

/**
 * `/repositories/*` route group (backend `app/api/routes/repositories.py`).
 *
 * Route params are UUIDs on the backend — the UI's owner/name URLs resolve
 * through `resolveId()` (one session-cached lookup per repository; see the
 * method for the resolution strategy). This replaces the phantom
 * `GET /repositories/{owner}/{repo}` path of Step 0.
 */
@Injectable({ providedIn: 'root' })
export class RepositoryService {
  private readonly api = inject(ApiService);

  /** Session cache: `owner/repo` (lowercased) → repository UUID. */
  private readonly idCache = new Map<string, string>();

  /** `GET /repositories` — paginated envelope, mapped to `Repository[]`. */
  getRepositories(params?: { page?: number; per_page?: number }): Observable<Repository[]> {
    // No params → the identical single-argument call as before (default
    // envelope; keeps existing expectations and the URL clean).
    const request = params
      ? this.api.get<RepositoryListDto>('/repositories', params)
      : this.api.get<RepositoryListDto>('/repositories');
    return request.pipe(map(toRepositoryList));
  }

  /**
   * Resolve `owner/name` → repository UUID for the UUID-scoped routes.
   *
   * Strategy: `GET /repositories?search=owner/name&per_page=100` (backend
   * `ilike`s name/full_name) followed by an exact case-insensitive
   * `full_name` match on the returned items — the fuzzy search may return
   * neighbours (`acme/api-v2`), the exact match never does. Hits are cached
   * for the session.
   *
   * Not found: the service asks the backend for `GET /repositories/{NIL_UUID}`
   * so the caller receives the backend's real 404 (interceptor → /not-found,
   * component error state) rather than a client-synthesized error.
   * There is no exact lookup endpoint on the backend yet — recorded in
   * docs/BACKEND_GAPS_FOR_UI.md.
   */
  resolveId(owner: string, name: string): Observable<string> {
    const key = `${owner}/${name}`.toLowerCase();
    const cached = this.idCache.get(key);
    if (cached) {
      return of(cached);
    }
    return this.api
      .get<RepositoryListDto>('/repositories', { search: `${owner}/${name}`, per_page: 100 })
      .pipe(
        switchMap(list => {
          const match = (list?.items ?? []).find(
            item => (item.full_name ?? '').toLowerCase() === key
          );
          if (match) {
            this.idCache.set(key, match.id);
            return of(match.id);
          }
          // Genuine backend 404 (see doc comment).
          return this.api.get<RepositoryDto>(`/repositories/${NIL_UUID}`).pipe(
            map(() => {
              throw new Error('unreachable: a nonexistent repository cannot be found');
            })
          );
        })
      );
  }

  /** Legacy `GET /repositories/github` (kept for the connect fallback). */
  getGitHubRepositories(): Observable<GitHubRepo[]> {
    return this.api.get<GitHubRepo[]>('/repositories/github');
  }

  connectRepository(githubRepoId: number): Observable<Repository> {
    return this.api
      .post<RepositoryDto>(`/repositories/connect?github_repo_id=${githubRepoId}`, {})
      .pipe(map(toRepository));
  }

  /**
   * `GET /repositories/{uuid}` — resolves the owner/name URL segment first
   * (replaces the phantom `GET /repositories/{owner}/{repo}`).
   */
  getRepository(owner: string, repo: string): Observable<Repository> {
    return this.resolveId(owner, repo).pipe(
      switchMap(id => this.api.get<RepositoryDto>(`/repositories/${id}`)),
      map(toRepository)
    );
  }

  /**
   * `GET /repositories/{uuid}/detail` — resolves the owner/name URL segment
   * first; adds the header stats (`total_prs`, `total_reviews`) and the
   * always-default `settings` block (read-only, proposal #17).
   */
  getRepositoryDetail(owner: string, repo: string): Observable<RepositoryDetail> {
    return this.resolveId(owner, repo).pipe(
      switchMap(id => this.api.get<RepositoryDetailDto>(`/repositories/${id}/detail`)),
      map(toRepositoryDetail)
    );
  }

  /**
   * `PATCH /repositories/{uuid}` — the only fields the API accepts today
   * (`enabled` / `default_branch`; see docs/BACKEND_GAPS_FOR_UI.md #17).
   */
  updateRepository(
    id: string,
    patch: { enabled?: boolean; default_branch?: string }
  ): Observable<Repository> {
    return this.api.patch<RepositoryDto>(`/repositories/${id}`, patch).pipe(map(toRepository));
  }

  enableRepository(id: string): Observable<Repository> {
    return this.api.post<Repository>(`/repositories/${id}/enable`, {});
  }

  disableRepository(id: string): Observable<Repository> {
    return this.api.post<Repository>(`/repositories/${id}/disable`, {});
  }

  deleteRepository(id: string): Observable<void> {
    return this.api.delete<void>(`/repositories/${id}`);
  }
}
