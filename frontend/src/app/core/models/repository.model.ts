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

/**
 * `settings` block of `GET /repositories/{id}/detail` — the backend always
 * answers with the schema defaults (nothing persists them yet, see
 * docs/BACKEND_GAPS_FOR_UI.md #17), so the Settings tab renders these
 * read-only.
 */
export interface RepositorySettings {
  autoReview: boolean;
  reviewOnPush: boolean;
  notifyOnFailure: boolean;
  maxFilesPerReview: number;
}

/** `GET /repositories/{id}/detail` — Repository + header stats + settings. */
export interface RepositoryDetail extends Repository {
  totalPrs: number;
  totalReviews: number;
  settings: RepositorySettings;
}
