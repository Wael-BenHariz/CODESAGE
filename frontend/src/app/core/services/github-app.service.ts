import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { ApiService } from './api.service';
import { GitHubAppRepo, GitHubInstallStatus } from '../models/github-app.model';

/**
 * GitHub App route group (backend `app/api/routes/github_repos.py`):
 * `GET /github/status`, `GET /github/repos`,
 * `POST /github/repos/selection`.
 *
 * The signed install URL lives under `/auth` and is served by
 * `AuthService.getInstallUrl()` (same "never build the GitHub URL by hand"
 * contract: its `state` is a JWT the callback verifies).
 */
@Injectable({ providedIn: 'root' })
export class GithubAppService {
  private readonly api = inject(ApiService);

  private readonly _githubInstalled = signal<boolean | null>(null);
  readonly githubInstalled = this._githubInstalled.asReadonly();

  /** GitHub App install status for the current user; keeps the shared signal in sync. */
  getInstallStatus(): Observable<GitHubInstallStatus> {
    return this.api
      .get<GitHubInstallStatus>('/github/status')
      .pipe(tap(status => this._githubInstalled.set(status.installed)));
  }

  /** Repositories accessible through the user's GitHub App installation. */
  getAppRepos(): Observable<GitHubAppRepo[]> {
    return this.api.get<GitHubAppRepo[]>('/github/repos');
  }

  /** Persist watched (review-enabled) repositories for the current user. */
  saveRepoSelection(repos: GitHubAppRepo[]): Observable<{ saved: boolean }> {
    // sync: true → payload is the complete desired state; backend disables
    // watched repos missing from it (makes selection two-way / deselectable).
    return this.api.post<{ saved: boolean }>('/github/repos/selection', { repos, sync: true });
  }
}
