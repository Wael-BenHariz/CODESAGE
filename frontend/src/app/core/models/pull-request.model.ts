/** `PullRequestResponse.state` vocabulary; anything else maps to `unknown`. */
export type PullRequestState = 'open' | 'closed' | 'merged' | 'unknown';

/**
 * Latest-review status as `PullRequestWithReviews` reports it. Unknown or
 * missing backend values map to `unknown` (safe display, never a guess).
 */
export type PullRequestReviewState =
  | 'pending'
  | 'processing'
  | 'in_progress'
  | 'ready_to_post'
  | 'completed'
  | 'failed'
  | 'unknown';

/**
 * Pointer to the PR's latest review (`latest_review_id` +
 * `latest_review_status` on `GET /pull-requests/{uuid}`). It carries NO
 * comment/issue counts — the backend response has none. The PR page's stats
 * bar derives them from the shared `GET /reviews/{id}` call (see
 * `deriveReviewStats` in pull-request.mapper.ts and docs/BACKEND_GAPS_FOR_UI.md).
 */
export interface PullRequestReviewRef {
  status: PullRequestReviewState;
  reviewId: string;
}

export interface PullRequest {
  id: string;
  repositoryId: string;
  number: number;
  title: string;
  body: string | null;
  state: PullRequestState;
  author: PRAuthor;
  baseBranch: string;
  headBranch: string;
  additions: number;
  deletions: number;
  changedFiles: number;
  reviewStatus: PullRequestReviewRef | null;
  createdAt: string;
  updatedAt: string;
}

export interface PRAuthor {
  login: string;
  avatarUrl: string;
}

export interface DiffFile {
  path: string;
  filename: string;
  status: 'added' | 'modified' | 'removed' | 'renamed';
  additions: number;
  deletions: number;
  binary: boolean;
  patch: string;
}

export interface DiffHunk {
  header: string;
  lines: DiffLine[];
}

export interface DiffLine {
  type: 'add' | 'remove' | 'context';
  content: string;
  oldLineNumber: number | null;
  newLineNumber: number | null;
}
