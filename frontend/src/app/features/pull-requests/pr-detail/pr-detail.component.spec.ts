import { TestBed, ComponentFixture } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { PrDetailComponent } from './pr-detail.component';
import { AuthService } from '../../../core/services/auth.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { ReviewService } from '../../../core/services/review.service';
import { OrgSettingsService } from '../../../core/services/org-settings.service';
import { PullRequest } from '../../../core/models/pull-request.model';

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

  beforeEach(() => {
    roleSignal = signal({ role: 'DEVELOPER' });
    pullRequests = jasmine.createSpyObj<PullRequestService>('PullRequestService', [
      'getPullRequest',
      'triggerReview',
      'getPullRequestReviews'
    ]);
    reviewApi = jasmine.createSpyObj<ReviewService>('ReviewService', ['getReviewDetail']);
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
});
