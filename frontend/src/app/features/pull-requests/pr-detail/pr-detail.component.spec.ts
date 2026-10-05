import { TestBed, ComponentFixture } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { NEVER, Subject, of, throwError } from 'rxjs';

import { PrDetailComponent } from './pr-detail.component';
import { ReviewPanelComponent } from '../review-panel/review-panel.component';
import { ApiError } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { ReviewService } from '../../../core/services/review.service';
import { OrgSettingsService } from '../../../core/services/org-settings.service';
import { PullRequest } from '../../../core/models/pull-request.model';
import { ReviewDetail, ReviewSummary } from '../../../core/models/review.model';

describe('PrDetailComponent — load error state (F3 pre-check b)', () => {
  let fixture: ComponentFixture<PrDetailComponent>;
  let pullRequests: jasmine.SpyObj<PullRequestService>;
  let reviewApi: jasmine.SpyObj<ReviewService>;
  let roleSignal: WritableSignal<{ role: string } | null>;

  const pr: PullRequest = {
    id: 'pr-1',
    repositoryId: 'repo-1',
    number: 7,
    title: 'Fix the thing',
    body: null,
    state: 'open',
    author: { login: 'octocat', avatarUrl: '' },
    baseBranch: 'main',
    headBranch: 'fix',
    additions: 10,
    deletions: 2,
    changedFiles: 3,
    reviewStatus: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-02T00:00:00Z'
  };

  /** Same PR, but with a latest review — the stats tiles' trigger. */
  const prWithReview: PullRequest = {
    ...pr,
    reviewStatus: { status: 'completed', reviewId: 'rev-1' }
  };

  /** One row of `GET /pull-requests/{id}/reviews` (ReviewSummary shape). */
  const reviewSummary: ReviewSummary = {
    id: 'rev-1',
    pull_request_id: 'pr-1',
    user_id: null,
    status: 'completed',
    error_message: null,
    summary: null,
    posting_mode: 'auto',
    posted_at: null,
    edited_summary: null,
    github_review_id: null,
    overall_severity: 'warning',
    created_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:05:00Z'
  };

  let invalidations$: Subject<string>;

  beforeEach(() => {
    roleSignal = signal({ role: 'DEVELOPER' });
    invalidations$ = new Subject<string>();
    pullRequests = jasmine.createSpyObj<PullRequestService>('PullRequestService', [
      'getPullRequest',
      'triggerReview',
      'getPullRequestReviews'
    ]);
    reviewApi = jasmine.createSpyObj<ReviewService>('ReviewService', [
      'getReviewDetail',
      'getScanReport'
    ]);
    // The component subscribes to the invalidation stream (readonly prop —
    // createSpyObj only spies methods, so attach the Subject by hand).
    Object.assign(reviewApi, { reviewDetailInvalidated$: invalidations$.asObservable() });
    // Default scan report: no findings/failures → adds nothing to the panel.
    reviewApi.getScanReport.and.returnValue(
      of({
        scan_id: 'scan-1',
        review_id: 'rev-1',
        tools_run: [],
        tools_failed: [],
        summary: {},
        findings: [],
        created_at: '2026-01-01T00:05:00Z'
      })
    );
    // The embedded review panel loads on PR success — default to "no reviews".
    pullRequests.getPullRequestReviews.and.returnValue(of([]));
    reviewApi.getReviewDetail.and.returnValue(
      of({
        id: 'rev-1',
        pull_request_id: 'pr-1',
        user_id: null,
        status: 'completed',
        error_message: null,
        summary: null,
        posting_mode: 'auto',
        posted_at: null,
        edited_summary: null,
        github_review_id: null,
        overall_severity: null,
        created_at: '2026-01-01T00:00:00Z',
        completed_at: null,
        comments_count: 0,
        comments: [],
        viewer_role: 'DEVELOPER'
      })
    );
    pullRequests.triggerReview.and.returnValue(
      of({ review_id: 'rev-1', status: 'pending', message: 'queued' })
    );

    TestBed.configureTestingModule({
      imports: [PrDetailComponent],
      providers: [
        provideRouter([]), // the component template uses RouterLink
        { provide: PullRequestService, useValue: pullRequests },
        { provide: ReviewService, useValue: reviewApi },
        // <app-site-header> → AuthContextService needs the org list API.
        { provide: OrgSettingsService, useValue: { listOrgs: () => of([]) } },
        // The component only reads currentUser()?.role.
        { provide: AuthService, useValue: { currentUser: roleSignal } }
      ]
    });
  });

  function create(): void {
    fixture = TestBed.createComponent(PrDetailComponent);
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.componentRef.setInput('number', 7);
    fixture.detectChanges(); // ngOnInit → getPullRequest (sync of()/throwError)
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders an explicit error state instead of a blank page when the load fails', () => {
    pullRequests.getPullRequest.and.returnValue(
      throwError(() => ({ status: 404, message: 'Pull request not found' }))
    );
    create();

    const errorEl = el().querySelector('[data-testid="pr-load-error"]');
    expect(errorEl).not.toBeNull();
    expect(errorEl?.textContent).toContain("Couldn't load this pull request");
    expect(fixture.componentInstance.loadError()).toBeTrue();
    expect(fixture.componentInstance.pullRequest()).toBeNull();
  });

  it('retries the load from the error state and renders the PR on success', () => {
    pullRequests.getPullRequest.and.returnValue(
      throwError(() => ({ status: 404, message: 'Pull request not found' }))
    );
    create();

    pullRequests.getPullRequest.and.returnValue(of(pr));
    (el().querySelector('[data-testid="pr-load-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges(); // the retry is synchronous; refresh the DOM

    expect(fixture.componentInstance.loadError()).toBeFalse();
    expect(el().querySelector('[data-testid="pr-load-error"]')).toBeNull();
    expect(el().querySelector('h1')?.textContent).toContain('Fix the thing');
    expect(pullRequests.getPullRequest).toHaveBeenCalledTimes(2);
  });

  it('renders the PR detail when the load succeeds (no error state)', () => {
    pullRequests.getPullRequest.and.returnValue(of(pr));
    create();

    expect(el().querySelector('[data-testid="pr-load-error"]')).toBeNull();
    expect(el().querySelector('h1')?.textContent).toContain('Fix the thing');
    expect(el().textContent).toContain('Start AI Review'); // DEVELOPER + nav().write
  });

  // --- stats bar from the shared GET /reviews/{id} (plan Step 2, Q1) --------

  /**
   * `GET /reviews/{id>` fixture: 5 comments, the first `dismissed` ones
   * flagged — counts must mirror what the review panel lists.
   */
  function reviewDetailFixture(dismissed: number): ReviewDetail {
    const comments = [1, 2, 3, 4, 5].map(n => ({
      id: `c${n}`,
      review_id: 'rev-1',
      file_path: `src/file${n}.py`,
      line_number: n,
      body: `finding ${n}`,
      severity: 'warning',
      category: 'correctness',
      resolved: false,
      dismissed: n <= dismissed,
      created_at: '2026-01-01T00:05:00Z',
      tool: 'semgrep',
      rule_id: 'rule',
      cwe: null,
      line_start: n,
      line_end: n,
      snippet: null,
      also_detected_by: null,
      validations: []
    }));
    return {
      ...reviewSummary,
      comments_count: 5,
      comments,
      viewer_role: 'DEVELOPER'
    };
  }

  it('hides the tiles and skips the extra request when the PR has no review', () => {
    pullRequests.getPullRequest.and.returnValue(of(pr)); // reviewStatus: null
    create();

    expect(reviewApi.getReviewDetail).not.toHaveBeenCalled();
    expect(el().querySelector('[data-testid="stat-comments"]')).toBeNull();
    expect(el().querySelector('[data-testid="stat-open-issues"]')).toBeNull();
  });

  it('shows — (never 0) while the review request is in flight', () => {
    pullRequests.getPullRequest.and.returnValue(of(prWithReview));
    reviewApi.getReviewDetail.and.returnValue(NEVER);
    create();

    expect(el().querySelector('[data-testid="stat-comments"]')?.textContent).toContain('—');
    expect(el().querySelector('[data-testid="stats-retry"]')).toBeNull(); // still loading
    expect(el().querySelector('[data-testid="pr-load-error"]')).toBeNull(); // PR stays
  });

  it('derives the tiles from the review: 5 comments, 2 dismissed → 5 and 3', () => {
    pullRequests.getPullRequest.and.returnValue(of(prWithReview));
    reviewApi.getReviewDetail.and.returnValue(of(reviewDetailFixture(2)));
    create();

    expect(el().querySelector('[data-testid="stat-comments"]')?.textContent?.trim()).toBe('5');
    expect(el().querySelector('[data-testid="stat-open-issues"]')?.textContent?.trim()).toBe('3');
    expect(el().textContent).toContain('open issues');
    expect(reviewApi.getReviewDetail).toHaveBeenCalledTimes(1);
  });

  it('the open-issues tile and the panel agree on the same fixture', () => {
    pullRequests.getPullRequest.and.returnValue(of(prWithReview));
    pullRequests.getPullRequestReviews.and.returnValue(of([reviewSummary]));
    reviewApi.getReviewDetail.and.returnValue(of(reviewDetailFixture(2)));
    create();

    const tile = Number(
      el().querySelector('[data-testid="stat-open-issues"]')?.textContent?.trim()
    );
    const rows = Array.from(el().querySelectorAll('[data-testid="review-comment"]'));
    const activeRows = rows.filter(row => !row.classList.contains('dismissed'));

    expect(rows.length).toBe(5); // dismissed are muted, not hidden
    expect(activeRows.length).toBe(3);
    expect(tile).toBe(activeRows.length);
  });

  it('a failed review request keeps the PR page; tiles show — + retry (never 0)', () => {
    pullRequests.getPullRequest.and.returnValue(of(prWithReview));
    reviewApi.getReviewDetail.and.returnValue(throwError(() => ({ status: 500, message: 'boom' })));
    create();

    expect(el().querySelector('h1')?.textContent).toContain('Fix the thing');
    expect(el().textContent).toContain('+10'); // PR stats still render
    const commentsTile = el().querySelector('[data-testid="stat-comments"]')?.textContent ?? '';
    expect(commentsTile).toContain('—');
    expect(commentsTile).not.toContain('0');
    const retry = el().querySelector('[data-testid="stats-retry"]') as HTMLButtonElement;
    expect(retry).not.toBeNull();

    // Retry recovers → real numbers (a zero only ever means a real zero).
    reviewApi.getReviewDetail.and.returnValue(of(reviewDetailFixture(2)));
    retry.click();
    fixture.detectChanges();
    expect(el().querySelector('[data-testid="stat-comments"]')?.textContent?.trim()).toBe('5');
    expect(el().querySelector('[data-testid="stats-retry"]')).toBeNull();
  });

  it('a 404 on the review shows no partial stats (the interceptor takes over)', () => {
    pullRequests.getPullRequest.and.returnValue(of(prWithReview));
    reviewApi.getReviewDetail.and.returnValue(
      throwError(() => new ApiError('Review not found', 404, 'Review not found'))
    );
    create();

    expect(el().querySelector('[data-testid="stat-comments"]')).toBeNull();
    expect(el().querySelector('[data-testid="stat-open-issues"]')).toBeNull();
    expect(el().querySelector('[data-testid="stats-retry"]')).toBeNull();
    expect(el().querySelector('h1')?.textContent).toContain('Fix the thing'); // page intact
  });

  it('refetches the tiles when a panel mutation invalidates the shared cache', () => {
    pullRequests.getPullRequest.and.returnValue(of(prWithReview));
    let calls = 0;
    reviewApi.getReviewDetail.and.callFake(() =>
      of(calls++ === 0 ? reviewDetailFixture(2) : reviewDetailFixture(3))
    );
    create();
    expect(el().querySelector('[data-testid="stat-open-issues"]')?.textContent?.trim()).toBe('3');

    invalidations$.next('rev-1'); // e.g. the panel dismissed one finding
    fixture.detectChanges();

    expect(el().querySelector('[data-testid="stat-comments"]')?.textContent?.trim()).toBe('5');
    expect(el().querySelector('[data-testid="stat-open-issues"]')?.textContent?.trim()).toBe('2');
    expect(reviewApi.getReviewDetail).toHaveBeenCalledTimes(2);
  });

  it('ignores invalidation events for a different review id', () => {
    pullRequests.getPullRequest.and.returnValue(of(prWithReview));
    reviewApi.getReviewDetail.and.returnValue(of(reviewDetailFixture(2)));
    create();

    invalidations$.next('some-other-review');
    fixture.detectChanges();

    expect(reviewApi.getReviewDetail).toHaveBeenCalledTimes(1);
    expect(el().querySelector('[data-testid="stat-open-issues"]')?.textContent?.trim()).toBe('3');
  });

  it('hasUnsavedSummaryEdit mirrors the embedded panel editor (plan Step 4)', () => {
    pullRequests.getPullRequest.and.returnValue(of(pr));
    create(); // panel renders (no reviews → its "none" state, still alive)

    // Nothing unsaved → the canDeactivate guard lets navigation through.
    expect(fixture.componentInstance.hasUnsavedSummaryEdit()).toBeFalse();

    // A dirty summary edit → the guard must ask before leaving.
    const panel = fixture.debugElement.query(By.directive(ReviewPanelComponent))
      ?.componentInstance as ReviewPanelComponent;
    panel.editingSummary.set(true);
    panel.summaryDraft.set('dirty');
    expect(fixture.componentInstance.hasUnsavedSummaryEdit()).toBeTrue();

    // Saving (or cancelling) the editor clears the warning.
    panel.editingSummary.set(false);
    expect(fixture.componentInstance.hasUnsavedSummaryEdit()).toBeFalse();
  });
});

describe('PrDetailComponent — shared review cache (one request per page load)', () => {
  let fixture: ComponentFixture<PrDetailComponent>;
  let httpMock: HttpTestingController;
  let pullRequests: jasmine.SpyObj<PullRequestService>;

  const pr: PullRequest = {
    id: 'pr-1',
    repositoryId: 'repo-1',
    number: 7,
    title: 'Fix the thing',
    body: null,
    state: 'open',
    author: { login: 'octocat', avatarUrl: '' },
    baseBranch: 'main',
    headBranch: 'fix',
    additions: 10,
    deletions: 2,
    changedFiles: 3,
    reviewStatus: { status: 'completed', reviewId: 'rev-1' },
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-02T00:00:00Z'
  };

  const reviewSummary: ReviewSummary = {
    id: 'rev-1',
    pull_request_id: 'pr-1',
    user_id: null,
    status: 'completed',
    error_message: null,
    summary: null,
    posting_mode: 'auto',
    posted_at: null,
    edited_summary: null,
    github_review_id: null,
    overall_severity: 'warning',
    created_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:05:00Z'
  };

  const detailBody = {
    ...reviewSummary,
    comments_count: 5,
    comments: [1, 2, 3, 4, 5].map(n => ({
      id: `c${n}`,
      review_id: 'rev-1',
      file_path: `src/file${n}.py`,
      line_number: n,
      body: `finding ${n}`,
      severity: 'warning',
      category: 'correctness',
      resolved: false,
      dismissed: n <= 2,
      created_at: '2026-01-01T00:05:00Z',
      tool: null,
      rule_id: null,
      cwe: null,
      line_start: n,
      line_end: n,
      snippet: null,
      also_detected_by: null,
      validations: []
    })),
    viewer_role: 'DEVELOPER'
  };

  beforeEach(() => {
    pullRequests = jasmine.createSpyObj<PullRequestService>('PullRequestService', [
      'getPullRequest',
      'triggerReview',
      'getPullRequestReviews'
    ]);
    pullRequests.getPullRequest.and.returnValue(of(pr));
    pullRequests.getPullRequestReviews.and.returnValue(of([reviewSummary]));
    pullRequests.triggerReview.and.returnValue(
      of({ review_id: 'rev-1', status: 'pending', message: 'queued' })
    );

    TestBed.configureTestingModule({
      imports: [PrDetailComponent],
      providers: [
        provideRouter([]),
        // REAL ReviewService over the testing backend — the shared cache is
        // the behavior under test, so it must not be mocked here.
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: PullRequestService, useValue: pullRequests },
        { provide: OrgSettingsService, useValue: { listOrgs: () => of([]) } },
        { provide: AuthService, useValue: { currentUser: () => ({ role: 'DEVELOPER' }) } }
      ]
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('stats bar + review panel share ONE GET /reviews/{id} per page load', () => {
    fixture = TestBed.createComponent(PrDetailComponent);
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.componentRef.setInput('number', 7);
    fixture.detectChanges(); // PR + reviews list load; both consumers ask for rev-1

    // Exactly ONE detail request — the second consumer joined the shared one.
    const open = httpMock.match(req => req.url.endsWith('/reviews/rev-1'));
    expect(open.length).toBe(1);
    // The panel's parallel enrichment fetch (plan Step 3) — one of those, too.
    const scans = httpMock.match(req => req.url.endsWith('/scan-report'));
    expect(scans.length).toBe(1);

    open[0].flush(detailBody);
    scans[0].flush({
      scan_id: 'scan-1',
      review_id: 'rev-1',
      tools_run: [],
      tools_failed: [],
      summary: {},
      findings: [],
      created_at: '2026-01-01T00:05:00Z'
    });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="stat-comments"]')?.textContent?.trim()).toBe('5');
    expect(el.querySelector('[data-testid="stat-open-issues"]')?.textContent?.trim()).toBe('3');
    expect(el.querySelectorAll('[data-testid="review-comment"]').length).toBe(5);

    // Nothing else hit the network during the page load.
    httpMock.expectNone(() => true);
  });
});
