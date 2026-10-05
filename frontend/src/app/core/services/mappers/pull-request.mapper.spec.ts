import {
  PullRequestListDto,
  PullRequestWithReviewsDto,
  deriveReviewStats,
  toPullRequestDetail,
  toPullRequestList,
  toPullRequestState
} from './pull-request.mapper';
import { ReviewDetail } from '../../models/review.model';

/** Real `PullRequestResponse` wire shape (schemas/pull_request.py). */
const PR_DTO = {
  id: 'pr-uuid-7',
  repository_id: 'repo-uuid-1',
  github_pr_id: 77,
  number: 7,
  title: 'Add rate limiter',
  body: 'Body text',
  state: 'open',
  author_login: 'octocat',
  author_avatar_url: 'https://avatars.example/1.png',
  base_branch: 'main',
  head_branch: 'feat/rate-limit',
  base_sha: 'abc123',
  head_sha: 'def456',
  additions: 12,
  deletions: 3,
  changed_files: 2,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z'
};

/** Minimal `ReviewComment` fixture — only the fields the stats derive from. */
function comment(id: string, dismissed: boolean) {
  return {
    id,
    dismissed,
    severity: 'warning',
    resolved: false,
    validations: []
  };
}

describe('pull-request.mapper', () => {
  describe('toPullRequestList (GET /pull-requests/repository/{id} fixture)', () => {
    it('maps the envelope rows snake_case → camelCase', () => {
      const dto: PullRequestListDto = {
        items: [PR_DTO],
        total: 1,
        page: 1,
        per_page: 100,
        pages: 1
      };

      const [row] = toPullRequestList(dto);

      expect(row.id).toBe('pr-uuid-7');
      expect(row.repositoryId).toBe('repo-uuid-1');
      expect(row.number).toBe(7);
      expect(row.author).toEqual({ login: 'octocat', avatarUrl: 'https://avatars.example/1.png' });
      expect(row.baseBranch).toBe('main');
      expect(row.headBranch).toBe('feat/rate-limit');
      expect(row.changedFiles).toBe(2);
      // List rows carry no review fields on the wire → never a guess.
      expect(row.reviewStatus).toBeNull();
    });

    it('tolerates null/missing optionals and an unknown state without throwing', () => {
      const sparse = {
        id: 'pr-uuid-8',
        number: 8,
        state: 'reopened',
        body: null,
        author_login: null,
        author_avatar_url: null
      };
      const dto: PullRequestListDto = {
        items: [sparse],
        total: 1,
        page: 1,
        per_page: 100,
        pages: 1
      };

      const [row] = toPullRequestList(dto);

      expect(row.state).toBe('unknown');
      expect(row.title).toBe('');
      expect(row.body).toBeNull();
      expect(row.author).toEqual({ login: '', avatarUrl: '' });
      expect(row.additions).toBe(0);
      expect(row.createdAt).toBe('');
    });

    it('a missing or empty envelope maps to an empty list (empty state, not a crash)', () => {
      expect(toPullRequestList({} as PullRequestListDto)).toEqual([]);
      expect(toPullRequestList({ items: null } as unknown as PullRequestListDto)).toEqual([]);
    });
  });

  describe('toPullRequestState', () => {
    it('passes the backend vocabulary through', () => {
      expect(toPullRequestState('open')).toBe('open');
      expect(toPullRequestState('closed')).toBe('closed');
      expect(toPullRequestState('merged')).toBe('merged');
      expect(toPullRequestState('MERGED')).toBe('merged');
    });

    it('unknown / null / missing → safe `unknown`, never a guess', () => {
      expect(toPullRequestState('reopened')).toBe('unknown');
      expect(toPullRequestState(null)).toBe('unknown');
      expect(toPullRequestState(undefined)).toBe('unknown');
      expect(toPullRequestState('')).toBe('unknown');
    });
  });

  describe('toPullRequestDetail (GET /pull-requests/{uuid} fixture)', () => {
    it('adds the latest-review pointer and keeps the base mapping', () => {
      const dto: PullRequestWithReviewsDto = {
        ...PR_DTO,
        reviews_count: 3,
        latest_review_id: 'rev-1',
        latest_review_status: 'completed'
      };

      const pr = toPullRequestDetail(dto);

      expect(pr.reviewStatus).toEqual({ status: 'completed', reviewId: 'rev-1' });
      expect(pr.number).toBe(7);
    });

    it('no latest review → no pointer (stats stay hidden, no extra request)', () => {
      const pr = toPullRequestDetail({
        ...PR_DTO,
        reviews_count: 0,
        latest_review_id: null,
        latest_review_status: null
      });

      expect(pr.reviewStatus).toBeNull();
    });

    it('an unknown latest_review_status maps to `unknown`, still pointing at the review', () => {
      const pr = toPullRequestDetail({
        ...PR_DTO,
        latest_review_id: 'rev-2',
        latest_review_status: 'queued'
      });

      expect(pr.reviewStatus).toEqual({ status: 'unknown', reviewId: 'rev-2' });
    });
  });

  describe('deriveReviewStats (GET /reviews/{id} fixture)', () => {
    it('counts comments as returned and open issues as dismissed = false', () => {
      // Required fixture: 5 comments, 2 dismissed → 5 and 3.
      const detail = {
        comments_count: 5,
        comments: [
          comment('c1', false),
          comment('c2', false),
          comment('c3', false),
          comment('c4', true),
          comment('c5', true)
        ]
      } as unknown as ReviewDetail;

      expect(deriveReviewStats(detail)).toEqual({ comments: 5, openIssues: 3 });
    });

    it('a real zero stays a zero (one undismissed comment → 1 open issue)', () => {
      const detail = {
        comments_count: 3,
        comments: [comment('c1', false), comment('c2', true), comment('c3', true)]
      } as unknown as ReviewDetail;

      expect(deriveReviewStats(detail)).toEqual({ comments: 3, openIssues: 1 });
    });

    it('comments_count missing but a complete list present → length is used', () => {
      const detail = {
        comments: [comment('c1', false), comment('c2', false)]
      } as unknown as ReviewDetail;

      expect(deriveReviewStats(detail)).toEqual({ comments: 2, openIssues: 2 });
    });

    it('list missing → open issues unavailable (null, never 0)', () => {
      const detail = { comments_count: 4 } as unknown as ReviewDetail;

      expect(deriveReviewStats(detail)).toEqual({ comments: 4, openIssues: null });
    });

    it('nothing usable → both unavailable (null, never 0)', () => {
      expect(deriveReviewStats({} as ReviewDetail)).toEqual({ comments: null, openIssues: null });
      expect(deriveReviewStats(null as unknown as ReviewDetail)).toEqual({
        comments: null,
        openIssues: null
      });
    });
  });
});
