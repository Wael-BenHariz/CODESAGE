export interface Repository {
  id: string;
  name: string;
  fullName: string;
  owner: string;
  description: string | null;
  private: boolean;
  defaultBranch: string;
  language: string | null;
  stars: number;
  forks: number;
  openIssues: number;
  webhookEnabled: boolean;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface RepositoryStats {
  totalRepositories: number;
  enabledRepositories: number;
  totalPullRequests: number;
  pendingReviews: number;
}
