export interface PullRequest {
  id: string;
  repositoryId: string;
  number: number;
  title: string;
  body: string | null;
  state: 'open' | 'closed' | 'merged';
  author: PRAuthor;
  baseBranch: string;
  headBranch: string;
  additions: number;
  deletions: number;
  changedFiles: number;
  reviewStatus: ReviewStatus | null;
  createdAt: string;
  updatedAt: string;
}

export interface PRAuthor {
  login: string;
  avatarUrl: string;
}

export interface ReviewStatus {
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  reviewId: string | null;
  commentCount: number;
  issueCount: number;
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
