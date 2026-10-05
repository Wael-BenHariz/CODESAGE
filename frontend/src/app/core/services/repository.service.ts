import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { ApiService } from './api.service';
import { Repository } from '../models/repository.model';
import { GitHubRepo } from '../models/github-app.model';
import {
  RepositoryDto,
  RepositoryListDto,
  toRepository,
  toRepositoryList
} from './mappers/repository.mapper';

/**
 * `/repositories/*` route group (backend `app/api/routes/repositories.py`).
 *
 * Path/mapping fixes for the phantom calls live in Step 2 — this service is
 * the route-group boundary the mapping layer hangs off.
 */
@Injectable({ providedIn: 'root' })
export class RepositoryService {
  private readonly api = inject(ApiService);

  /** `GET /repositories` — paginated envelope, mapped to `Repository[]`. */
  getRepositories(): Observable<Repository[]> {
    return this.api.get<RepositoryListDto>('/repositories').pipe(map(toRepositoryList));
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

  getRepository(owner: string, repo: string): Observable<Repository> {
    return this.api.get<Repository>(`/repositories/${owner}/${repo}`);
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
