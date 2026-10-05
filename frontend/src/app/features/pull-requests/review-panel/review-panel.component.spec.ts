import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { ReviewPanelComponent } from './review-panel.component';
import { ApiError } from '../../../core/services/api.service';
import { GithubService } from '../../../core/services/github.service';
import { ReviewComment, ReviewDetail, ReviewSummary } from '../../../core/models/review.model';

describe('ReviewPanelComponent — read-only panel states (plan Step 7b)', () => {
  let fixture: ComponentFixture<ReviewPanelComponent>;
  let github: jasmine.SpyObj<GithubService>;

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

  beforeEach(() => {
    github = jasmine.createSpyObj<GithubService>('GithubService', [
      'getPullRequestReviews',
      'getReviewDetail',
      'triggerReview',
      'postReview',
      'updateReviewSummary',
      'dismissReviewComment',
      'restoreReviewComment'
    ]);
    github.getPullRequestReviews.and.returnValue(of([]));
    github.getReviewDetail.and.returnValue(of(detail()));
    github.triggerReview.and.returnValue(
      of({ review_id: 'rev-1', status: 'pending', message: 'queued' })
    );
    github.postReview.and.returnValue(
      of({
        review_id: 'rev-1',
        github_review_id: 987,
        posted_at: '2026-01-01T00:06:00Z',
        message: 'Review posted to GitHub'
      })
    );
    github.updateReviewSummary.and.returnValue(
      of({
        review_id: 'rev-1',
        summary: 'Original summary.',
        edited_summary: null,
        status: 'ready_to_post',
        posted_at: null
      })
    );
    github.dismissReviewComment.and.returnValue(of(comment()));
    github.restoreReviewComment.and.returnValue(of(comment({ dismissed: false })));

    TestBed.configureTestingModule({
      imports: [ReviewPanelComponent],
      providers: [provideRouter([]), { provide: GithubService, useValue: github }]
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
    github.getPullRequestReviews.and.returnValue(of([]));
    create();

    expect(testid('review-panel-none')).not.toBeNull();
    const cta = testid('review-cta') as HTMLButtonElement;
    expect(cta).not.toBeNull();
    expect(cta.textContent).toContain('Run AI Review');

    cta.click();
    expect(github.triggerReview).toHaveBeenCalledWith('pr-1');
    // After triggering, the panel reloads to show the pending review.
    expect(github.getPullRequestReviews).toHaveBeenCalledTimes(2);
  });

  it('hides the CTA for viewers without write access and reports a failed trigger', () => {
    github.getPullRequestReviews.and.returnValue(of([]));
    github.triggerReview.and.returnValue(throwError(() => ({ status: 403 })));
    create(false);

    expect(testid('review-panel-none')).not.toBeNull();
    expect(testid('review-cta')).toBeNull();
    expect(github.triggerReview).not.toHaveBeenCalled();

    // A trigger failure surfaces as an inline error, not a silent no-op.
    create(true);
    (testid('review-cta') as HTMLButtonElement).click();
    fixture.detectChanges(); // the click set triggerError — flush it to the DOM
    expect(testid('review-trigger-error')).not.toBeNull();
    expect(testid('review-panel-none')).not.toBeNull();
  });

  // --- pending / processing ----------------------------------------------------

  it('shows a spinner while the latest review is pending', () => {
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'pending' })]));
    github.getReviewDetail.and.returnValue(of(detail({ status: 'pending' })));
    create();

    expect(testid('review-panel-running')).not.toBeNull();
    expect(testid('review-panel-running')?.textContent).toContain('pending');
    expect(testid('review-summary')).toBeNull();
  });

  it('shows a spinner while the latest review is processing', () => {
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'processing' })]));
    github.getReviewDetail.and.returnValue(of(detail({ status: 'processing' })));
    create();

    expect(testid('review-panel-running')).not.toBeNull();
    expect(testid('review-panel-running')?.textContent).toContain('processing');
  });

  // --- failed ----------------------------------------------------------------

  it('shows the failure message when the review failed', () => {
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'failed' })]));
    github.getReviewDetail.and.returnValue(
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
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'ready_to_post' })]));
    github.getReviewDetail.and.returnValue(of(detail({ status: 'ready_to_post' }, comments)));
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
    github.getPullRequestReviews.and.returnValue(
      of([
        summary({ status: 'completed', posted_at: '2026-01-01T00:06:00Z', github_review_id: 555 })
      ])
    );
    github.getReviewDetail.and.returnValue(
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
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    github.getReviewDetail.and.returnValue(of(detail({ status: 'completed' }, [])));
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
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    github.getReviewDetail.and.returnValue(of(detail({ status: 'completed' }, comments)));
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
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    github.getReviewDetail.and.returnValue(
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
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    github.getReviewDetail.and.returnValue(
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
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'ready_to_post' })]));
    github.getReviewDetail.and.returnValue(
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
    github.getPullRequestReviews.and.returnValue(
      throwError(() => ({ status: 404, message: 'Pull request not found' }))
    );
    create();

    expect(testid('review-panel-error')).not.toBeNull();

    github.getPullRequestReviews.and.returnValue(of([]));
    (testid('review-retry') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(testid('review-panel-error')).toBeNull();
    expect(testid('review-panel-none')).not.toBeNull();
    expect(github.getPullRequestReviews).toHaveBeenCalledTimes(2);
  });

  it('errors when the review detail itself cannot be loaded', () => {
    github.getPullRequestReviews.and.returnValue(of([summary({ status: 'completed' })]));
    github.getReviewDetail.and.returnValue(throwError(() => ({ status: 500 })));
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
      github.getPullRequestReviews.and.returnValue(of([summary({ status: 'ready_to_post' })]));
      github.getReviewDetail.and.returnValue(
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
      expect(github.postReview).not.toHaveBeenCalled(); // confirming is required
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
      github.getPullRequestReviews.and.returnValue(
        of([
          summary({
            status: 'completed',
            posted_at: '2026-01-01T00:06:00Z',
            github_review_id: 777
          })
        ])
      );
      github.getReviewDetail.and.returnValue(
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

      expect(github.postReview).toHaveBeenCalledWith('rev-1');
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
      github.postReview.and.returnValue(
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
      github.postReview.and.returnValue(
        of({
          review_id: 'rev-1',
          github_review_id: 987,
          posted_at: '2026-01-01T00:07:00Z',
          message: 'ok'
        })
      );
      github.getPullRequestReviews.and.returnValue(
        of([
          summary({
            status: 'completed',
            posted_at: '2026-01-01T00:07:00Z',
            github_review_id: 987
          })
        ])
      );
      github.getReviewDetail.and.returnValue(
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

      expect(github.postReview).toHaveBeenCalledTimes(2);
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

      github.updateReviewSummary.and.returnValue(
        of({
          review_id: 'rev-1',
          summary: 'Original summary.',
          edited_summary: 'Edited by hand.',
          status: 'ready_to_post',
          posted_at: null
        })
      );
      (testid('save-summary') as HTMLButtonElement).click();

      expect(github.updateReviewSummary).toHaveBeenCalledWith('rev-1', 'Edited by hand.');
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
      github.dismissReviewComment.and.returnValue(of({ ...baseComment(), dismissed: true }));
      (testid('dismiss-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(github.dismissReviewComment).toHaveBeenCalledWith('rev-1', 'c-1');
      expect(testid('comment-dismissed')).not.toBeNull();
      expect(testid('dismiss-finding')).toBeNull();
      expect(testid('restore-finding')).not.toBeNull();

      github.restoreReviewComment.and.returnValue(of(baseComment()));
      (testid('restore-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(github.restoreReviewComment).toHaveBeenCalledWith('rev-1', 'c-1');
      expect(testid('comment-dismissed')).toBeNull();
      expect(testid('dismiss-finding')).not.toBeNull();
      expect(testid('restore-finding')).toBeNull();
    });

    it('surfaces a dismiss API failure visibly and leaves the button usable', () => {
      createReady();
      github.dismissReviewComment.and.returnValue(
        throwError(() => new ApiError('Comment not found', 404, 'Comment not found'))
      );
      (testid('dismiss-finding') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(testid('api-error')?.textContent).toContain('Comment not found');
      expect(testid('comment-dismissed')).toBeNull(); // state did not change
      expect((testid('dismiss-finding') as HTMLButtonElement).disabled).toBeFalse();
    });
  });
});
