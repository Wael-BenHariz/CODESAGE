/**
 * GitHub App route group (`GET /github/status`, `GET /github/repos`,
 * `POST /github/repos/selection`) — shapes mirror the backend responses
 * (backend `app/api/routes/github_repos.py`).
 */

/** One repository as GitHub returns it (GET /github/repos). */
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

/** GET /github/status — shared install state for the whole app. */
export interface GitHubInstallStatus {
  installed: boolean;
  installation_id: number | null;
}

/** One repo in the selection list (GET/POST /github/repos[...]). */
export interface GitHubAppRepo {
  id: number;
  /** GitHub repository full name (owner/repo). */
  name: string;
  private: boolean;
  enabled: boolean;
}
