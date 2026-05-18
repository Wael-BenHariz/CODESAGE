import { Injectable, inject } from '@angular/core';
import { ApiService } from './api.service';
import { Observable, map } from 'rxjs';
import { Repository, RepositoryStats } from '../models/repository.model';
import { PullRequest } from '../models/pull-request.model';

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
    updatedAt: raw.updated_at,
  };
}

@Injectable({
  providedIn: 'root'
})
export class GithubService {
  private readonly api = inject(ApiService);

  getRepositories(): Observable<Repository[]> {
    return this.api.get<PaginatedResponse<any>>('/repositories').pipe(
      map(response => response.items.map(mapRepo))
    );
  }

  getGitHubRepositories(): Observable<GitHubRepo[]> {
    return this.api.get<GitHubRepo[]>('/repositories/github');
  }

  connectRepository(githubRepoId: number): Observable<Repository> {
    return this.api.post<any>(`/repositories/connect?github_repo_id=${githubRepoId}`, {}).pipe(
      map(mapRepo)
    );
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

  triggerReview(prId: string): Observable<{ reviewId: string }> {
    return this.api.post<{ reviewId: string }>(`/pulls/${prId}/review`, {});
  }

  getReviewStatus(reviewId: string): Observable<{ status: string; progress: number }> {
    return this.api.get<{ status: string; progress: number }>(`/reviews/${reviewId}/status`);
  }
}