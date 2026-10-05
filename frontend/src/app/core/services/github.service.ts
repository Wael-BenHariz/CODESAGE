import { Injectable, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import { Observable, map, tap } from 'rxjs';
import { Repository, RepositoryStats } from '../models/repository.model';
import { PullRequest } from '../models/pull-request.model';
import { ReviewDetail, ReviewSummary } from '../models/review.model';

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface GitHubRepo {
  id: number;
  name: string;
  full_name: string;
  private: boolean;
  default_branch: string;
  description: string | null;
  language: string | null;
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
}

export interface GitHubInstallStatus {
  installed: boolean;
  installation_id: number | null;
}

export interface GitHubAppRepo {
  id: number;
  /** GitHub repository full name (owner/repo). */
  name: string;
  private: boolean;
  enabled: boolean;
}

function mapRepo(raw: any): Repository {
  const owner = raw.full_name?.split('/')[0] || '';
  return {
    id: raw.id,
    name: raw.name,
    fullName: raw.full_name,
    owner,
    description: raw.description,
    private: raw.private,
    defaultBranch: raw.default_branch,
    language: raw.language,
    stars: raw.stars ?? 0,
    forks: raw.forks ?? 0,
    openIssues: raw.open_issues ?? 0,
    webhookEnabled: raw.webhook_enabled ?? false,
    enabled: raw.enabled,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at
  };
}

@Injectable({
  providedIn: 'root'
})
export class GithubService {
  private readonly api = inject(ApiService);

  private readonly _githubInstalled = signal<boolean | null>(null);
  readonly githubInstalled = this._githubInstalled.asReadonly();

  getRepositories(): Observable<Repository[]> {
    return this.api
      .get<PaginatedResponse<any>>('/repositories')
      .pipe(map(response => response.items.map(mapRepo)));
  }

  getGitHubRepositories(): Observable<GitHubRepo[]> {
    return this.api.get<GitHubRepo[]>('/repositories/github');
  }

  /**
   * Signed GitHub App installation URL. The `state` claim is a JWT signed with
   * STATE_TOKEN_SECRET so the /auth/github/app/callback endpoint can identify
   * the installing user — never construct the GitHub URL manually.
   */
  getInstallUrl(): Observable<{ url: string }> {
    return this.api.get<{ url: string }>('/auth/github/app/install-url');
  }

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

  connectRepository(githubRepoId: number): Observable<Repository> {
    return this.api
      .post<any>(`/repositories/connect?github_repo_id=${githubRepoId}`, {})
      .pipe(map(mapRepo));
  }

  getRepository(owner: string, repo: string): Observable<Repository> {
    return this.api.get<Repository>(`/repositories/${owner}/${repo}`);
  }

  getRepositoryStats(): Observable<RepositoryStats> {
    return this.api.get<RepositoryStats>('/repositories/stats');
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

  getPullRequests(repoId: string, state?: string): Observable<PullRequest[]> {
    const params: Record<string, string | number> = {};
    if (state) {
      params['state'] = state;
    }
    return this.api.get<PullRequest[]>(`/repositories/${repoId}/pulls`, params);
  }

  getPullRequest(owner: string, repo: string, number: number): Observable<PullRequest> {
    return this.api.get<PullRequest>(`/pulls/${owner}/${repo}/${number}`);
  }

  triggerReview(prId: string): Observable<{ review_id: string; status: string; message: string }> {
    // The backend mounts this router at /pull-requests — the previous
    // /pulls path never existed upstream (POST /pull-requests/{id}/review).
    return this.api.post<{ review_id: string; status: string; message: string }>(
      `/pull-requests/${prId}/review`,
      {}
    );
  }

  getReviewStatus(reviewId: string): Observable<{ status: string; progress: number }> {
    return this.api.get<{ status: string; progress: number }>(`/reviews/${reviewId}/status`);
  }

  /** All reviews for a pull request, newest first (review panel input). */
  getPullRequestReviews(prId: string): Observable<ReviewSummary[]> {
    return this.api.get<ReviewSummary[]>(`/pull-requests/${prId}/reviews`);
  }

  /** Full review detail: summary + comments with enrichment and viewer_role. */
  getReviewDetail(reviewId: string): Observable<ReviewDetail> {
    return this.api.get<ReviewDetail>(`/reviews/${reviewId}`);
  }
}
