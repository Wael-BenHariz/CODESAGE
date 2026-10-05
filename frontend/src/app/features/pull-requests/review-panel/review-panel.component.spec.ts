import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';

import { ReviewPanelComponent } from './review-panel.component';
import {
  indexScanFindings,
  matchScanFinding,
  uncoveredScanFindings
} from './review-panel.component';
import { ApiError } from '../../../core/services/api.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { ReviewService } from '../../../core/services/review.service';
import {
  CommentValidation,
  ReviewComment,
  ReviewDetail,
  ReviewSummary,
  ScanFinding,
  ScanReport
} from '../../../core/models/review.model';

describe('ReviewPanelComponent — read-only panel states (plan Step 7b)', () => {
  let fixture: ComponentFixture<ReviewPanelComponent>;
  let pullRequests: jasmine.SpyObj<PullRequestService>;
  let reviewApi: jasmine.SpyObj<ReviewService>;

  const summary = (over: Partial<ReviewSummary> = {}): ReviewSummary => ({
    id: 'rev-1',
    pull_request_id: 'pr-1',
    user_id: 'user-1',
    status: 'completed',
    error_message: null,
    summary: 'Original summary.',
    posting_mode: 'auto',
    posted_at: null,
    edited_summary: null,
    github_review_id: null,
    overall_severity: 'warning',
    created_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:05:00Z',
    ...over
  });

  const comment = (over: Partial<ReviewComment> = {}): ReviewComment => ({
    id: 'c-1',
    review_id: 'rev-1',
    file_path: 'src/a.py',
    line_number: 10,
    body: 'Something looks off.',
    severity: 'info',
    category: 'style',
    resolved: false,
    dismissed: false,
    created_at: '2026-01-01T00:05:00Z',
    tool: null,
    rule_id: null,
    cwe: null,
    line_start: null,
    line_end: null,
    snippet: null,
    also_detected_by: null,
    validations: [],
    ...over
  });

  const detail = (
    over: Partial<ReviewDetail> = {},
    comments: ReviewComment[] = []
  ): ReviewDetail => ({
    ...summary(over),
    comments_count: comments.length,
    comments,
    viewer_role: 'DEVELOPER',
    ...over
  });

  /** Real `NormalizedFinding` fixture (services/normalizers/schema.py). */
  const scanFinding = (over: Partial<ScanFinding> = {}): ScanFinding => ({
    id: 'f-1',
    tool: 'semgrep',
    rule_id: 'python.lang.security.audit.sqli',
    title: 'SQL injection',
    message: 'User input flows into a query.',
    severity: 'high',
    category: 'vulnerability',
    file_path: 'src/a.py',
    line_start: 10,
    line_end: 12,
    snippet: null,
    cwe: ['CWE-89'],
    owasp: ['A03:2021-Injection'],
    references: [],
    also_detected_by: [],
    fix_suggestion: 'Use a parameterized query.',
    raw: {},
    ...over
  });

  /** Real `ScanReportResponse` fixture (schemas/scan_report.py). */
  const scanReport = (over: Partial<ScanReport> = {}): ScanReport => ({
    scan_id: 'scan-1',
    review_id: 'rev-1',
    tools_run: ['sonarqube', 'semgrep'],
    tools_failed: [],
    summary: { total: 0, by_severity: {}, by_tool: {} },
    findings: [],
    created_at: '2026-01-01T00:05:00Z',
    ...over
  });

  beforeEach(() => {
    pullRequests = jasmine.createSpyObj<PullRequestService>('PullRequestService', [
      'getPullRequestReviews',
      'triggerReview'
    ]);
    reviewApi = jasmine.createSpyObj<ReviewService>('ReviewService', [
      'getReviewDetail',
      'getScanReport',
      'postReview',
      'updateReviewSummary',
      'dismissReviewComment',
      'restoreReviewComment',
      'validateReviewFinding'
    ]);
    pullRequests.getPullRequestReviews.and.returnValue(of([]));
    reviewApi.getReviewDetail.and.returnValue(of(detail()));
    // Default: a report with no findings → no visible enrichment, so the
    // pre-Step-3 state tests stay byte-identical.
    reviewApi.getScanReport.and.returnValue(of(scanReport()));
    pullRequests.triggerReview.and.returnValue(
      of({ review_id: 'rev-1', status: 'pending', message: 'queued' })
    );
    reviewApi.postReview.and.returnValue(
      of({
        review_id: 'rev-1',
        github_review_id: 987,
        posted_at: '2026-01-01T00:06:00Z',
        message: 'Review posted to GitHub'
      })
    );
    reviewApi.updateReviewSummary.and.returnValue(
      of({
        review_id: 'rev-1',
        summary: 'Original summary.',
        edited_summary: null,
        status: 'ready_to_post',
        posted_at: null
      })
    );
    reviewApi.dismissReviewComment.and.returnValue(of(comment()));
    reviewApi.restoreReviewComment.and.returnValue(of(comment({ dismissed: false })));

    TestBed.configureTestingModule({
      imports: [ReviewPanelComponent],
      providers: [
        provideRouter([]),
        { provide: PullRequestService, useValue: pullRequests },
        { provide: ReviewService, useValue: reviewApi }
      ]
    });
  });

  function create(canTrigger = true): void {
    fixture = TestBed.createComponent(ReviewPanelComponent);
    fixture.componentRef.setInput('prId', 'pr-1');
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.componentRef.setInput('number', 7);
    fixture.componentRef.setInput('canTrigger', canTrigger);
    fixture.detectChanges(); // ngOnInit → load (sync of()/throwError)
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function testid(id: string): HTMLElement | null {
    return el().querySelector(`[data-testid="${id}"]`);
  }

  // --- none state ------------------------------------------------------------

  it('shows the call to action when the PR has no review yet', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([]));
    create();

    expect(testid('review-panel-none')).not.toBeNull();
    const cta = testid('review-cta') as HTMLButtonElement;
    expect(cta).not.toBeNull();
    expect(cta.textContent).toContain('Run AI Review');

    cta.click();
    expect(pullRequests.triggerReview).toHaveBeenCalledWith('pr-1');
    // After triggering, the panel reloads to show the pending review.
    expect(pullRequests.getPullRequestReviews).toHaveBeenCalledTimes(2);
  });

  it('hides the CTA for viewers without write access and reports a failed trigger', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([]));
    pullRequests.triggerReview.and.returnValue(throwError(() => ({ status: 403 })));
    create(false);

    expect(testid('review-panel-none')).not.toBeNull();
    expect(testid('review-cta')).toBeNull();
    expect(pullRequests.triggerReview).not.toHaveBeenCalled();

    // A trigger failure surfaces as an inline error, not a silent no-op.
    create(true);
    (testid('review-cta') as HTMLButtonElement).click();
    fixture.detectChanges(); // the click set triggerError — flush it to the DOM
    expect(testid('review-trigger-error')).not.toBeNull();
    expect(testid('review-panel-none')).not.toBeNull();
  });

  // --- pending / processing ----------------------------------------------------

  it('shows a spinner while the latest review is pending', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'pending' })]));
    reviewApi.getReviewDetail.and.returnValue(of(detail({ status: 'pending' })));
    create();

    expect(testid('review-panel-running')).not.toBeNull();
    expect(testid('review-panel-running')?.textContent).toContain('pending');
    expect(testid('review-summary')).toBeNull();
  });

  it('shows a spinner while the latest review is processing', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'processing' })]));
    reviewApi.getReviewDetail.and.returnValue(of(detail({ status: 'processing' })));
    create();

    expect(testid('review-panel-running')).not.toBeNull();
    expect(testid('review-panel-running')?.textContent).toContain('processing');
  });

  // --- failed ----------------------------------------------------------------

  it('shows the failure message when the review failed', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'failed' })]));
    reviewApi.getReviewDetail.and.returnValue(
      of(
        detail({
          status: 'failed',
          error_message: 'LLM provider rejected the request',
          summary: null
        })
      )
    );
    create();

    expect(testid('review-panel-failed')).not.toBeNull();
    expect(testid('review-error-message')?.textContent).toContain(
      'LLM provider rejected the request'
    );
  });

  // --- ready_to_post (staged controls — Step 8) -------------------------------

  it('shows the ready-to-post badge with staged controls (Step 8)', () => {
    const comments = [comment({ severity: 'error', body: 'SQL injection risk' })];
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'ready_to_post' })]));
    reviewApi.getReviewDetail.and.returnValue(of(detail({ status: 'ready_to_post' }, comments)));
    create();

    expect(testid('review-ready-badge')).not.toBeNull();
    expect(testid('review-summary')?.textContent).toContain('Original summary.');
    expect(testid('review-gh-link')).toBeNull();
    // Step 8: banner + edit/dismiss controls for a DEVELOPER+ viewer…
    expect(testid('staged-banner')).not.toBeNull();
    expect(testid('open-post')).not.toBeNull();
    expect(testid('edit-summary')).not.toBeNull();
    expect(testid('dismiss-finding')).not.toBeNull();
    // viewer_role is exposed by GET /reviews/{id} for the gating.
    expect(fixture.componentInstance.detail()?.viewer_role).toBe('DEVELOPER');
  });

  // --- posted ------------------------------------------------------------------

  it('shows posted_at and the GitHub review link for a posted review', () => {
    pullRequests.getPullRequestReviews.and.returnValue(
      of([
        summary({ status: 'completed', posted_at: '2026-01-01T00:06:00Z', github_review_id: 555 })
      ])
    );
    reviewApi.getReviewDetail.and.returnValue(
      of(
        detail({
          status: 'completed',
          posted_at: '2026-01-01T00:06:00Z',
          github_review_id: 555
        })
      )
    );
    create();

    expect(testid('review-status')?.textContent).toContain('posted');
    expect(testid('review-posted-at')).not.toBeNull();
    expect(testid('review-posted-at')?.textContent?.trim().length).toBeGreaterThan(0);
    const link = testid('review-gh-link') as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe(
      'https://github.com/acme/demo/pulls/7#pullrequestreview-555'
    );
  });

  // --- zero findings -----------------------------------------------------------

  it('shows the empty state when the review has no findings', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    reviewApi.getReviewDetail.and.returnValue(of(detail({ status: 'completed' }, [])));
    create();

    expect(testid('review-panel-empty')).not.toBeNull();
    expect(testid('review-summary')?.textContent).toContain('Original summary.');
    expect(el().querySelector('[data-testid="review-comment"]')).toBeNull();
  });

  // --- findings rendering --------------------------------------------------------

  it('groups findings by file, sorted severity → file → line, with tool badges', () => {
    const comments = [
      comment({
        id: 'c-info',
        file_path: 'src/a.py',
        line_number: 3,
        severity: 'info',
        body: 'Nit'
      }),
      comment({
        id: 'c-err',
        file_path: 'src/b.py',
        line_number: 1,
        severity: 'error',
        body: 'Hard error',
        tool: 'sonarqube',
        rule_id: 'python:S2077',
        cwe: ['CWE-89'],
        line_start: 1,
        line_end: 4,
        snippet: 'query(f"...")',
        also_detected_by: ['semgrep']
      }),
      comment({
        id: 'c-warn',
        file_path: 'src/a.py',
        line_number: 10,
        severity: 'warning',
        body: 'Careful'
      })
    ];
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    reviewApi.getReviewDetail.and.returnValue(of(detail({ status: 'completed' }, comments)));
    create();

    // Files ordered by their strongest finding: b.py (error) before a.py.
    const groups = el().querySelectorAll('[data-testid="review-file-group"]');
    expect(groups.length).toBe(2);
    expect(groups[0].querySelector('.file-path')?.textContent).toContain('src/b.py');
    expect(groups[1].querySelector('.file-path')?.textContent).toContain('src/a.py');

    // Within a file: warning (line 10) before info (line 3).
    const aBodies = Array.from(groups[1].querySelectorAll('.comment-body')).map(n =>
      n.textContent?.trim()
    );
    expect(aBodies).toEqual(['Careful', 'Nit']);

    // Enrichment badges on the matched finding.
    const errorRow = groups[0].querySelector('[data-testid="review-comment"]') as HTMLElement;
    expect(errorRow.getAttribute('data-severity')).toBe('error');
    expect(errorRow.querySelector('[data-testid="comment-tool"]')?.textContent).toContain(
      'sonarqube'
    );
    expect(errorRow.querySelector('[data-testid="comment-also"]')?.textContent).toContain(
      'semgrep'
    );
    expect(errorRow.querySelector('[data-testid="comment-loc"]')?.textContent).toContain(
      'src/b.py:1'
    );
    expect(errorRow.textContent).toContain('python:S2077');
    expect(errorRow.textContent).toContain('CWE-89');
    expect(errorRow.textContent).toContain('finding lines 1–4');
    expect(errorRow.querySelector('[data-testid="comment-snippet"]')?.textContent).toContain(
      'query(f"...")'
    );
  });

  it('renders hostile comment text as plain text (no HTML injection)', () => {
    const hostile = '<img src=x onerror="alert(1)">';
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    reviewApi.getReviewDetail.and.returnValue(
      of(
        detail({ status: 'completed' }, [
          comment({ severity: 'warning', body: hostile, snippet: '<script>steal()</script>' })
        ])
      )
    );
    create();

    const row = testid('review-comment') as HTMLElement;
    expect(row.textContent).toContain(hostile); // visible as text…
    expect(row.querySelector('img')).toBeNull(); // …but never parsed as markup
    expect(row.querySelector('script')).toBeNull();
    expect(row.textContent).toContain('<script>steal()</script>');
  });

  it('mutes dismissed findings without hiding them', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    reviewApi.getReviewDetail.and.returnValue(
      of(
        detail({ status: 'completed' }, [
          comment({ id: 'c-1', severity: 'error', body: 'Kept', dismissed: false }),
          comment({ id: 'c-2', severity: 'warning', body: 'Dismissed', dismissed: true })
        ])
      )
    );
    create();

    const rows = el().querySelectorAll('[data-testid="review-comment"]');
    expect(rows.length).toBe(2); // dismissed is muted, not hidden
    const dismissed = el().querySelector('[data-testid="comment-dismissed"]');
    expect(dismissed).not.toBeNull();
    const dismissedRow = dismissed?.closest('.comment') as HTMLElement;
    expect(dismissedRow.classList.contains('dismissed')).toBeTrue();
    expect(dismissedRow.textContent).toContain('Dismissed');
  });

  it('prefers edited_summary over summary', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'ready_to_post' })]));
    reviewApi.getReviewDetail.and.returnValue(
      of(
        detail({
          status: 'ready_to_post',
          summary: 'Raw LLM summary.',
          edited_summary: 'Human-edited summary.'
        })
      )
    );
    create();

    expect(testid('review-summary')?.textContent).toContain('Human-edited summary.');
    expect(testid('review-summary')?.textContent).not.toContain('Raw LLM summary.');
  });

  // --- load error + retry -------------------------------------------------------

  it('shows an explicit error state and retries from it', () => {
    pullRequests.getPullRequestReviews.and.returnValue(
      throwError(() => ({ status: 404, message: 'Pull request not found' }))
    );
    create();

    expect(testid('review-panel-error')).not.toBeNull();

    pullRequests.getPullRequestReviews.and.returnValue(of([]));
    (testid('review-retry') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(testid('review-panel-error')).toBeNull();
    expect(testid('review-panel-none')).not.toBeNull();
    expect(pullRequests.getPullRequestReviews).toHaveBeenCalledTimes(2);
  });

  it('errors when the review detail itself cannot be loaded', () => {
    pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    reviewApi.getReviewDetail.and.returnValue(throwError(() => ({ status: 500 })));
    create();

    expect(testid('review-panel-error')).not.toBeNull();
    expect(testid('review-panel-running')).toBeNull();
  });

  // --- staged posting controls (plan Step 8) --------------------------------

  describe('staged posting controls (plan Step 8)', () => {
    const baseComment = (): ReviewComment =>
      comment({
        id: 'c-1',
        severity: 'error',
        body: 'SQL injection risk',
        file_path: 'src/a.py',
        line_number: 5
      });

    function createReady(
      over: Partial<ReviewDetail> = {},
      comments: ReviewComment[] = [baseComment()]
    ): void {
      pullRequests.getPullRequestReviews.and.returnValue(
        of([summary({ status: 'ready_to_post' })])
      );
      reviewApi.getReviewDetail.and.returnValue(
        of(detail({ status: 'ready_to_post', ...over }, comments))
      );
      create();
    }

    it('opens a confirmation dialog listing findings and the dismissed count', () => {
      createReady({}, [
        baseComment(),
        comment({
          id: 'c-2',
          severity: 'info',
          body: 'Nit',
          file_path: 'src/b.py',
          line_number: 9,
          dismissed: true
        })
      ]);
      expect(testid('staged-banner')).not.toBeNull();

      (testid('open-post') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(testid('post-dialog')).not.toBeNull();
      expect(reviewApi.postReview).not.toHaveBeenCalled(); // confirming is required
      const findings = el().querySelectorAll('[data-testid="dialog-finding"]');
      expect(findings.length).toBe(1); // dismissed findings are excluded
      expect(findings[0].textContent).toContain('src/a.py:5');
      expect(testid('dialog-dismissed')?.textContent).toContain('1 dismissed');

      (testid('cancel-post') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(testid('post-dialog')).toBeNull();
    });

    it('posts after confirmation and becomes read-only', () => {
      createReady();
      (testid('open-post') as HTMLButtonElement).click();
      fixture.detectChanges();

      // The POST triggers a re-fetch — serve the now-posted review.
      pullRequests.getPullRequestReviews.and.returnValue(
        of([
          summary({
            status: 'completed',
            posted_at: '2026-01-01T00:06:00Z',
            github_review_id: 777
          })
        ])
      );
      reviewApi.getReviewDetail.and.returnValue(
        of(
          detail({
            status: 'completed',
            posted_at: '2026-01-01T00:06:00Z',
            github_review_id: 777
          })
        )
      );

      (testid('confirm-post') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(reviewApi.postReview).toHaveBeenCalledWith('rev-1');
      expect(testid('post-dialog')).toBeNull();
      expect(testid('review-status')?.textContent).toContain('posted');
      expect(testid('review-gh-link')).not.toBeNull();
      // Controls are read-only after posting.
      expect(testid('staged-banner')).toBeNull();
      expect(testid('edit-summary')).toBeNull();
      expect(testid('dismiss-finding')).toBeNull();
    });

    it('keeps the dialog open and shows the error when posting fails', () => {
      createReady();
      reviewApi.postReview.and.returnValue(
        throwError(
          () => new ApiError('GitHub post failed (403): bad credentials', 403, 'bad credentials')
        )
      );
      (testid('open-post') as HTMLButtonElement).click();
      fixture.detectChanges();
      (testid('confirm-post') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(testid('post-dialog')).not.toBeNull();
      expect(testid('post-error')?.textContent).toContain('GitHub post failed (403)');
      expect(testid('api-error')).toBeNull(); // the dialog owns the error while open

      // Retryable: a second attempt succeeds.
      reviewApi.postReview.and.returnValue(
        of({
          review_id: 'rev-1',
          github_review_id: 987,
          posted_at: '2026-01-01T00:07:00Z',
          message: 'ok'
        })
      );
      pullRequests.getPullRequestReviews.and.returnValue(
        of([
          summary({
            status: 'completed',
            posted_at: '2026-01-01T00:07:00Z',
            github_review_id: 987
          })
        ])
      );
      reviewApi.getReviewDetail.and.returnValue(
        of(
          detail({
            status: 'completed',
            posted_at: '2026-01-01T00:07:00Z',
            github_review_id: 987
          })
        )
      );
      (testid('confirm-post') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(reviewApi.postReview).toHaveBeenCalledTimes(2);
      expect(testid('post-dialog')).toBeNull();
      expect(testid('review-status')?.textContent).toContain('posted');
    });

    it('gates every control off for a NONE viewer but keeps the content', () => {
      createReady({ viewer_role: 'NONE' });

      expect(testid('staged-banner')).toBeNull();
      expect(testid('open-post')).toBeNull();
      expect(testid('edit-summary')).toBeNull();
      expect(testid('dismiss-finding')).toBeNull();
      expect(testid('review-summary')).not.toBeNull(); // read-only, not hidden
    });

    it('edits the summary: prefill, dirty gating, save', () => {
      createReady();
      (testid('edit-summary') as HTMLButtonElement).click();
      fixture.detectChanges();

      const textarea = testid('summary-textarea') as HTMLTextAreaElement;
      expect(textarea.value).toBe('Original summary.');
      expect(textarea.getAttribute('maxlength')).toBe('60000'); // client-side cap
      expect((testid('save-summary') as HTMLButtonElement).disabled).toBeTrue(); // clean

      textarea.value = 'Edited by hand.';
      textarea.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(testid('summary-dirty')).not.toBeNull();
      expect((testid('save-summary') as HTMLButtonElement).disabled).toBeFalse();

      reviewApi.updateReviewSummary.and.returnValue(
        of({
          review_id: 'rev-1',
          summary: 'Original summary.',
          edited_summary: 'Edited by hand.',
          status: 'ready_to_post',
          posted_at: null
        })
      );
      (testid('save-summary') as HTMLButtonElement).click();

      expect(reviewApi.updateReviewSummary).toHaveBeenCalledWith('rev-1', 'Edited by hand.');
      fixture.detectChanges();
      expect(testid('summary-textarea')).toBeNull(); // editor closed
      expect(testid('review-summary')?.textContent).toContain('Edited by hand.');
    });

    it('warns before discarding a dirty summary edit', () => {
      createReady();
      (testid('edit-summary') as HTMLButtonElement).click();
      fixture.detectChanges();
      const textarea = testid('summary-textarea') as HTMLTextAreaElement;
      textarea.value = 'dirty';
      textarea.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      const confirmSpy = spyOn(window, 'confirm').and.returnValue(false);
      (testid('cancel-summary') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(confirmSpy).toHaveBeenCalled();
      expect(testid('summary-textarea')).not.toBeNull(); // kept editing

      confirmSpy.and.returnValue(true);
      (testid('cancel-summary') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(testid('summary-textarea')).toBeNull(); // discarded
    });

    it('dismisses a finding into the muted state and restores it back', () => {
      createReady();
      reviewApi.dismissReviewComment.and.returnValue(of({ ...baseComment(), dismissed: true }));
      (testid('dismiss-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(reviewApi.dismissReviewComment).toHaveBeenCalledWith('rev-1', 'c-1');
      expect(testid('comment-dismissed')).not.toBeNull();
      expect(testid('dismiss-finding')).toBeNull();
      expect(testid('restore-finding')).not.toBeNull();

      reviewApi.restoreReviewComment.and.returnValue(of(baseComment()));
      (testid('restore-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(reviewApi.restoreReviewComment).toHaveBeenCalledWith('rev-1', 'c-1');
      expect(testid('comment-dismissed')).toBeNull();
      expect(testid('dismiss-finding')).not.toBeNull();
      expect(testid('restore-finding')).toBeNull();
    });

    it('surfaces a dismiss API failure visibly and leaves the button usable', () => {
      createReady();
      reviewApi.dismissReviewComment.and.returnValue(
        throwError(() => new ApiError('Comment not found', 404, 'Comment not found'))
      );
      (testid('dismiss-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(testid('api-error')?.textContent).toContain('Comment not found');
      expect(testid('comment-dismissed')).toBeNull(); // state did not change
      expect((testid('dismiss-finding') as HTMLButtonElement).disabled).toBeFalse();
    });
  });

  // --- reviewer validation (plan Step 10) ----------------------------------

  describe('reviewer validation (plan Step 10)', () => {
    const validationRow = (over: Partial<CommentValidation> = {}): CommentValidation => ({
      verdict: 'confirmed',
      severity_override: null,
      note: null,
      reviewer_login: 'kc-reviewer-a',
      created_at: '2026-01-01T00:10:00Z',
      updated_at: '2026-01-01T00:10:00Z',
      ...over
    });

    const judgedComment = (): ReviewComment =>
      comment({
        id: 'c-1',
        severity: 'error',
        body: 'SQL injection risk',
        file_path: 'src/a.py',
        line_number: 5,
        validations: [validationRow({ note: 'True positive <script>alert(1)</script>' })]
      });

    const plainComment = (): ReviewComment =>
      comment({
        id: 'c-1',
        severity: 'error',
        body: 'SQL injection risk',
        file_path: 'src/a.py',
        line_number: 5
      });

    function createWithRole(viewer_role: string, comments: ReviewComment[]): void {
      pullRequests.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
      reviewApi.getReviewDetail.and.returnValue(
        of(detail({ status: 'completed', viewer_role }, comments))
      );
      create();
    }

    it('shows verdicts to every viewer but only renders controls for REVIEWER+', () => {
      createWithRole('DEVELOPER', [judgedComment()]);

      // Existing verdicts: who / what / when — visible below the threshold.
      expect(testid('verdict-list')).not.toBeNull();
      expect(testid('verdict-who')?.textContent).toContain('kc-reviewer-a');
      expect(testid('verdict-badge')?.textContent).toContain('confirmed');
      expect(testid('verdict-note')?.textContent).toContain('True positive');
      // The note renders as TEXT — interpolation escapes, never parsed markup.
      expect(el().querySelector('script')).toBeNull();
      expect(testid('validation-controls')).toBeNull();

      // Crossing the threshold (REVIEWER) unlocks the controls.
      createWithRole('REVIEWER', [judgedComment()]);
      expect(testid('verdict-list')).not.toBeNull();
      expect(testid('validation-controls')).not.toBeNull();
      expect(testid('confirm-finding')).not.toBeNull();
      expect(testid('fp-finding')).not.toBeNull();
      expect(testid('severity-override')).not.toBeNull();
      expect(testid('validation-note')).not.toBeNull();
    });

    it('optimistically shows my pending verdict and settles with the server row', () => {
      const response = new Subject<CommentValidation>();
      reviewApi.validateReviewFinding.and.returnValue(response);
      createWithRole('REVIEWER', [plainComment()]);

      (testid('confirm-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(reviewApi.validateReviewFinding).toHaveBeenCalledWith('rev-1', 'c-1', {
        verdict: 'confirmed',
        severity_override: null,
        note: null
      });
      // Optimistic row visible BEFORE the server answers.
      expect(testid('verdict-list')).not.toBeNull();
      expect(el().textContent).toContain('(you)');
      expect((testid('confirm-finding') as HTMLButtonElement).disabled).toBeTrue();

      response.next(
        validationRow({
          reviewer_login: 'octocat',
          created_at: '2026-01-01T00:20:00Z',
          updated_at: '2026-01-01T00:20:00Z'
        })
      );
      fixture.detectChanges();

      // Server row replaces the placeholder; controls re-enable.
      expect(testid('verdict-who')?.textContent).toContain('octocat');
      expect(el().textContent).not.toContain('(you)');
      expect((testid('confirm-finding') as HTMLButtonElement).disabled).toBeFalse();
    });

    it('sends the severity override + trimmed note draft with the verdict', () => {
      reviewApi.validateReviewFinding.and.returnValue(
        of(validationRow({ severity_override: 'warning', note: 'check authz' }))
      );
      createWithRole('REVIEWER', [plainComment()]);

      const select = testid('severity-override') as HTMLSelectElement;
      select.value = 'warning';
      select.dispatchEvent(new Event('change'));
      const noteInput = testid('validation-note') as HTMLInputElement;
      noteInput.value = '  check authz  ';
      noteInput.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      (testid('fp-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(reviewApi.validateReviewFinding).toHaveBeenCalledWith('rev-1', 'c-1', {
        verdict: 'false_positive',
        severity_override: 'warning',
        note: 'check authz'
      });
      // Draft cleared once the verdict landed; server row is displayed.
      expect((testid('severity-override') as HTMLSelectElement).value).toBe('');
      expect((testid('validation-note') as HTMLInputElement).value).toBe('');
      expect(el().textContent).toContain('kc-reviewer-a');
      expect(el().textContent).not.toContain('(you)');
    });

    it('rolls back the optimistic verdict and surfaces the API error', () => {
      const response = new Subject<CommentValidation>();
      reviewApi.validateReviewFinding.and.returnValue(response);
      createWithRole('REVIEWER', [judgedComment()]); // existing verdict by kc-reviewer-a

      (testid('fp-finding') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(el().textContent).toContain('(you)'); // optimistic row added alongside

      response.error(new ApiError('Verdict rejected (403)', 403, 'forbidden'));
      fixture.detectChanges();

      expect(el().textContent).not.toContain('(you)'); // rolled back
      expect(testid('verdict-who')?.textContent).toContain('kc-reviewer-a');
      expect(testid('api-error')?.textContent).toContain('Verdict rejected (403)');
      expect((testid('fp-finding') as HTMLButtonElement).disabled).toBeFalse();
    });
  });

  // --- scan-report enrichment (plan Step 3) ---------------------------------

  describe('scan-report enrichment (plan Step 3)', () => {
    it('renders the tools_failed header with the failing tool and reason', () => {
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getScanReport.and.returnValue(
        of(
          scanReport({
            tools_run: ['semgrep'],
            tools_failed: [{ tool: 'sonarqube', error: 'scanner timed out' }]
          })
        )
      );
      create();

      const notice = testid('scan-tools-failed');
      expect(notice).not.toBeNull();
      expect(notice?.textContent).toContain('Static analysis incomplete');
      expect(notice?.textContent).toContain('sonarqube: scanner timed out');
    });

    it('stays silent when the review has no scan report yet (404 = absence)', () => {
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getScanReport.and.returnValue(
        throwError(() => new ApiError('No scan report for this review', 404, 'no scan'))
      );
      create();

      expect(testid('scan-tools-failed')).toBeNull();
      expect(testid('scan-unavailable')).toBeNull();
      // The review itself still renders — no navigation, no broken panel.
      expect(testid('review-summary')).not.toBeNull();
      expect(testid('review-panel-empty')).not.toBeNull();
    });

    it('shows a muted note when the scan report fails transiently (non-404)', () => {
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getScanReport.and.returnValue(
        throwError(() => new ApiError('Server error', 500, 'boom'))
      );
      create();

      expect(testid('scan-unavailable')).not.toBeNull();
      expect(testid('scan-tools-failed')).toBeNull();
      expect(testid('review-summary')).not.toBeNull(); // comments unaffected
    });

    it('joins OWASP tags and the fix suggestion into the matched comment', () => {
      const enriched = comment({
        tool: 'semgrep',
        rule_id: 'python.lang.security.audit.sqli',
        file_path: 'src/a.py',
        line_number: 10,
        line_start: 10,
        line_end: 12
      });
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getReviewDetail.and.returnValue(of(detail({}, [enriched])));
      reviewApi.getScanReport.and.returnValue(of(scanReport({ findings: [scanFinding()] })));
      create();

      expect(testid('comment-owasp')?.textContent).toContain('A03:2021-Injection');
      expect(testid('comment-fix')?.textContent).toContain('Use a parameterized query.');
    });

    it('lists scan findings no comment covers — separately, with exact counts', () => {
      const matched = comment({
        tool: 'semgrep',
        rule_id: 'rule.matched',
        file_path: 'src/a.py',
        line_number: 10
      });
      const orphans = [1, 2].map(n =>
        scanFinding({
          id: `f-orphan-${n}`,
          rule_id: `rule.orphan.${n}`,
          file_path: `src/b${n}.py`,
          line_start: n,
          fix_suggestion: `Fix ${n}`
        })
      );
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getReviewDetail.and.returnValue(of(detail({}, [matched])));
      reviewApi.getScanReport.and.returnValue(
        of(
          scanReport({
            findings: [scanFinding({ id: 'f-covered', rule_id: 'rule.matched' }), ...orphans]
          })
        )
      );
      create();

      expect(testid('scan-only-findings')).not.toBeNull();
      expect(testid('scan-only-count')?.textContent?.trim()).toBe('2');
      const rows = el().querySelectorAll('[data-testid="scan-finding"]');
      expect(rows.length).toBe(2); // the covered finding is NOT listed
      expect(testid('scan-fix')?.textContent).toContain('Fix 1');
      // The covered comment shows its own enrichment instead.
      expect(testid('comment-owasp')).not.toBeNull();
      expect(testid('comment-fix')).not.toBeNull();
    });

    it('a report whose findings are all covered renders no standalone section', () => {
      const matched = comment({
        tool: 'semgrep',
        rule_id: 'python.lang.security.audit.sqli',
        line_number: 10
      });
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getReviewDetail.and.returnValue(of(detail({}, [matched])));
      reviewApi.getScanReport.and.returnValue(of(scanReport({ findings: [scanFinding()] })));
      create();

      expect(testid('scan-only-findings')).toBeNull();
    });

    it('caps the standalone list at 50 rows but keeps the exact total', () => {
      const findings = Array.from({ length: 55 }, (_, i) =>
        scanFinding({
          id: `f-${i}`,
          rule_id: `rule.${i}`,
          file_path: `src/x${i}.py`,
          line_start: i
        })
      );
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getScanReport.and.returnValue(of(scanReport({ findings })));
      create();

      expect(el().querySelectorAll('[data-testid="scan-finding"]').length).toBe(50);
      expect(testid('scan-only-count')?.textContent?.trim()).toBe('55');
      expect(testid('scan-more')?.textContent).toContain('5 more');
    });

    it('a report with no findings and no failures adds nothing to the panel', () => {
      pullRequests.getPullRequestReviews.and.returnValue(of([summary()]));
      reviewApi.getReviewDetail.and.returnValue(of(detail({}, [comment()])));
      reviewApi.getScanReport.and.returnValue(of(scanReport()));
      create();

      expect(testid('scan-tools-failed')).toBeNull();
      expect(testid('scan-unavailable')).toBeNull();
      expect(testid('scan-only-findings')).toBeNull();
      expect(testid('review-comment')).not.toBeNull(); // comments intact
    });
  });

  // --- pure join helpers (unit, no fixture needed) --------------------------

  describe('scan join helpers (pure functions)', () => {
    const index = indexScanFindings([scanFinding()]);

    it('matches a comment to its source finding by source rule + line', () => {
      const hit = matchScanFinding(
        comment({ tool: 'semgrep', rule_id: scanFinding().rule_id, line_number: 10 }),
        index
      );
      expect(hit?.id).toBe('f-1');
    });

    it('returns null for a comment with no source-rule columns (LLM-only)', () => {
      expect(matchScanFinding(comment(), index)).toBeNull(); // tool/rule are null
    });

    it('does not match a different line of the same rule', () => {
      const hit = matchScanFinding(
        comment({ tool: 'semgrep', rule_id: scanFinding().rule_id, line_number: 99 }),
        index
      );
      expect(hit).toBeNull();
    });

    it('a file-level comment (line null) matches its rule anywhere', () => {
      const hit = matchScanFinding(
        comment({ tool: 'semgrep', rule_id: scanFinding().rule_id, line_number: null }),
        index
      );
      expect(hit?.id).toBe('f-1');
    });

    it('uncovers only findings no comment covers (line-compatible)', () => {
      const findings = [
        scanFinding({ id: 'f-line' }),
        scanFinding({ id: 'f-other', rule_id: 'rule.other' })
      ];
      const everything = uncoveredScanFindings(
        [comment({ tool: 'semgrep', rule_id: 'rule.unrelated', line_number: 10 })],
        findings
      );
      expect(everything.map(f => f.id)).toEqual(['f-line', 'f-other']);

      const rest = uncoveredScanFindings(
        [comment({ tool: 'semgrep', rule_id: scanFinding().rule_id, line_number: 10 })],
        findings
      );
      expect(rest.map(f => f.id)).toEqual(['f-other']);
    });
  });
});
