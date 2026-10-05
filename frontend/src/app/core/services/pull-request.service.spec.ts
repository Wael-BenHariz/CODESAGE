import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { ApiError, ApiService } from './api.service';
import { PullRequestService } from './pull-request.service';
import { RepositoryService } from './repository.service';

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

function listEnvelope(items: unknown[], pages = 1) {
  return { items, total: items.length, page: 1, per_page: 100, pages };
}

describe('PullRequestService (/pull-requests group)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let repos: jasmine.SpyObj<RepositoryService>;
  let service: PullRequestService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post']);
    repos = jasmine.createSpyObj<RepositoryService>('RepositoryService', ['resolveId']);
    repos.resolveId.and.returnValue(of('repo-uuid-1'));
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: api },
        { provide: RepositoryService, useValue: repos }
      ]
    });
    service = TestBed.inject(PullRequestService);
  });

  it('lists PRs from GET /pull-requests/repository/{repository_id} (replaces the phantom path)', () => {
    api.get.and.returnValue(of(listEnvelope([PR_DTO])));

    let rows: unknown;
    service.getPullRequests('acme', 'demo').subscribe(prs => (rows = prs));

    expect(repos.resolveId).toHaveBeenCalledWith('acme', 'demo');
    expect(api.get).toHaveBeenCalledWith('/pull-requests/repository/repo-uuid-1', {
      per_page: 100
    });
    // snake_case wire → camelCase model (mapping layer, not component).
    expect((rows as { repositoryId: string }[])[0].repositoryId).toBe('repo-uuid-1');
    // List rows carry no review fields on the wire → null, never a guess.
    expect((rows as { reviewStatus: unknown }[])[0].reviewStatus).toBeNull();
  });

  it('passes the state filter alongside per_page on the PR list', () => {
    api.get.and.returnValue(of(listEnvelope([])));

    service.getPullRequests('acme', 'demo', 'open').subscribe();

    expect(api.get).toHaveBeenCalledWith('/pull-requests/repository/repo-uuid-1', {
      per_page: 100,
      state: 'open'
    });
  });

  it('resolves the PR number through a bounded list scan, then loads GET /pull-requests/{uuid}', () => {
    // Deterministic call order: scan p1 (no match) → scan p2 (match) → detail.
    api.get.and.returnValues(
      of(listEnvelope([], 2)),
      of(listEnvelope([PR_DTO], 2)),
      of({ ...PR_DTO, latest_review_id: 'rev-1', latest_review_status: 'completed' })
    );

    let pr: { reviewStatus: { status: string; reviewId: string } | null } | undefined;
    service.getPullRequest('acme', 'demo', 7).subscribe(value => (pr = value));

    expect(api.get).toHaveBeenCalledWith('/pull-requests/repository/repo-uuid-1', {
      per_page: 100,
      page: 1
    });
    expect(api.get).toHaveBeenCalledWith('/pull-requests/repository/repo-uuid-1', {
      per_page: 100,
      page: 2
    });
    expect(api.get).toHaveBeenCalledWith('/pull-requests/pr-uuid-7');
    expect(pr?.reviewStatus).toEqual({ status: 'completed', reviewId: 'rev-1' });
  });

  it('caches the by-number id: a second detail load skips the list scan', () => {
    // Order: scan (match at page 1) → detail → detail again (cache hit for the id).
    api.get.and.returnValues(
      of(listEnvelope([PR_DTO])),
      of({ ...PR_DTO, latest_review_id: null, latest_review_status: null }),
      of({ ...PR_DTO, latest_review_id: null, latest_review_status: null })
    );

    service.getPullRequest('acme', 'demo', 7).subscribe();
    const scanCallsAfterFirst = api.get.calls
      .allArgs()
      .filter(args => String(args[0]).startsWith('/pull-requests/repository/')).length;

    service.getPullRequest('acme', 'demo', 7).subscribe();

    const scanCallsAfterSecond = api.get.calls
      .allArgs()
      .filter(args => String(args[0]).startsWith('/pull-requests/repository/')).length;
    expect(scanCallsAfterSecond).toBe(scanCallsAfterFirst);
  });

  it('a number that scans nowhere ends in the backend 404 (nil UUID), not a silent blank', () => {
    // Order: empty scan → nil-UUID request fails with the backend's 404.
    api.get.and.returnValues(
      of(listEnvelope([], 1)),
      throwError(() => new ApiError('Pull request not found', 404, 'Pull request not found'))
    );

    let caught: unknown;
    service.getPullRequest('acme', 'demo', 999).subscribe({
      error: err => (caught = err)
    });

    expect(api.get).toHaveBeenCalledWith('/pull-requests/00000000-0000-0000-0000-000000000000');
    expect(caught instanceof ApiError).toBeTrue();
    expect((caught as ApiError).status).toBe(404);
  });

  it('triggers reviews on the backend mount point /pull-requests/{id}/review', () => {
    api.post.and.returnValue(of({ review_id: 'r1', status: 'pending', message: 'ok' }));

    service.triggerReview('pr-9').subscribe();

    expect(api.post).toHaveBeenCalledWith('/pull-requests/pr-9/review', {});
  });

  it('lists PR reviews from /pull-requests/{id}/reviews', () => {
    api.get.and.returnValue(of([]));

    service.getPullRequestReviews('pr-9').subscribe();

    expect(api.get).toHaveBeenCalledWith('/pull-requests/pr-9/reviews');
  });
});
