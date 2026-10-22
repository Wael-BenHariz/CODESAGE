import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, Router } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { KeycloakService } from 'keycloak-angular';

import { ReviewListComponent } from './review-list.component';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { ReviewService } from '../../../core/services/review.service';
import { ApiError } from '../../../core/services/api.service';
import { ReviewSummary } from '../../../core/models/review.model';
import { PullRequest } from '../../../core/models/pull-request.model';
import { Repository } from '../../../core/models/repository.model';

describe('ReviewListComponent — cross-repo review history (GET /reviews)', () => {
  let fixture: ComponentFixture<ReviewListComponent>;
  let component: ReviewListComponent;
  let reviewApi: jasmine.SpyObj<ReviewService>;
  let pullRequests: jasmine.SpyObj<PullRequestService>;
  let repositories: jasmine.SpyObj<RepositoryService>;
  let navigate: jasmine.Spy;

  const review = (id: string, extra: Partial<ReviewSummary> = {}): ReviewSummary => ({
    id,
    pull_request_id: `pr-${id}`,
    user_id: null,
    status: 'completed',
    error_message: null,
    summary: `Summary of ${id}`,
    posting_mode: 'auto',
    posted_at: '2026-10-08T08:42:12Z',
    edited_summary: null,
    github_review_id: 123,
    overall_severity: 'error',
    started_at: '2026-10-08T08:42:00Z',
    created_at: '2026-10-08T08:41:00Z',
    completed_at: '2026-10-08T08:42:12Z',
    ...extra
  });

  const pr = (id: string): PullRequest => ({
    id,
    repositoryId: 'repo-1',
    number: 482,
    title: 'A pull request',
    body: null,
    state: 'open',
    author: { login: 'octocat', avatarUrl: '' },
    baseBranch: 'main',
    headBranch: 'feature',
    additions: 10,
    deletions: 2,
    changedFiles: 3,
    reviewStatus: null,
    createdAt: '2026-10-08T08:00:00Z',
    updatedAt: '2026-10-08T08:00:00Z'
  });

  const repo = (): Repository => ({
    id: 'repo-1',
    owner: 'acme',
    name: 'api',
    fullName: 'acme/api',
    description: null,
    private: false,
    defaultBranch: 'main',
    language: null,
    stars: 0,
    forks: 0,
    openIssues: 0,
    webhookEnabled: false,
    enabled: true,
    createdAt: '',
    updatedAt: '',
    orgId: null,
    orgName: null
  });

  /** Two completed reviews + one staged awaiting its post. */
  const pageOne: ReviewSummary[] = [
    review('r-1'),
    review('r-2', { status: 'ready_to_post', posted_at: null, overall_severity: null }),
    review('r-3', {
      status: 'failed',
      overall_severity: null,
      posted_at: null,
      github_review_id: null,
      error_message: 'diff too large'
    })
  ];

  beforeEach(async () => {
    reviewApi = jasmine.createSpyObj<ReviewService>('ReviewService', ['listReviews']);
    reviewApi.listReviews.and.returnValue(
      of({ items: pageOne, total: 25, page: 1, per_page: 20, pages: 2 })
    );
    pullRequests = jasmine.createSpyObj<PullRequestService>('PullRequestService', [
      'getPullRequestById'
    ]);
    pullRequests.getPullRequestById.and.returnValue(of(pr('pr-r-1')));
    repositories = jasmine.createSpyObj<RepositoryService>('RepositoryService', [
      'getRepositoryById'
    ]);
    repositories.getRepositoryById.and.returnValue(of(repo()));

    await TestBed.configureTestingModule({
      imports: [ReviewListComponent],
      providers: [
        provideHttpClient(),
        provideRouter([]),
        { provide: ReviewService, useValue: reviewApi },
        { provide: PullRequestService, useValue: pullRequests },
        { provide: RepositoryService, useValue: repositories },
        {
          provide: KeycloakService,
          useValue: jasmine.createSpyObj<KeycloakService>('KeycloakService', ['isLoggedIn'])
        }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ReviewListComponent);
    component = fixture.componentInstance;
    navigate = spyOn(TestBed.inject(Router), 'navigate');
    fixture.detectChanges(); // ngOnInit → load()
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('lists the reviews with status, severity and staged/posted chips', () => {
    expect(reviewApi.listReviews).toHaveBeenCalledWith(1, 20, undefined);
    const rows = el().querySelectorAll('[data-testid^="review-row-"]');
    expect(rows.length).toBe(3);
    const text = el().textContent ?? '';
    expect(text).toContain('completed');
    expect(text).toContain('critical'); // overall_severity error → critical badge
    expect(text).toContain('awaiting post');
    expect(text).toContain('posted');
  });

  it('expands a row to reveal the summary and metadata', () => {
    expect(component.isExpanded('r-1')).toBeFalse();
    component.toggle('r-1');
    fixture.detectChanges();

    const expanded = el().querySelector('[data-testid="review-expanded-r-1"]');
    expect(expanded).not.toBeNull();
    expect(expanded?.textContent).toContain('Summary of r-1');
    expect(expanded?.textContent).toContain('Posting mode');
  });

  it('filters by status through the backend status_filter param', () => {
    const select = el().querySelector('[data-testid="reviews-status-filter"]') as HTMLSelectElement;
    select.value = 'failed';
    component.onFilterChange({ target: select } as unknown as Event);

    expect(component.statusFilter()).toBe('failed');
    expect(component.page()).toBe(1);
    expect(reviewApi.listReviews).toHaveBeenCalledWith(1, 20, 'failed');
  });

  it('paginates with the envelope totals', () => {
    expect(component.pages()).toBe(2);
    component.nextPage();
    expect(reviewApi.listReviews).toHaveBeenCalledWith(2, 20, undefined);
    component.prevPage();
    expect(reviewApi.listReviews).toHaveBeenCalledWith(1, 20, undefined);
  });

  it('renders the empty state with filter-aware copy', () => {
    reviewApi.listReviews.and.returnValue(
      of({ items: [], total: 0, page: 1, per_page: 20, pages: 1 })
    );
    component.load();
    fixture.detectChanges();

    const empty = el().querySelector('[data-testid="reviews-empty"]');
    expect(empty).not.toBeNull();
    expect(empty?.textContent).toContain('Reviews appear here');
  });

  it('shows the error state with retry and reloads on click', () => {
    let fail = true;
    reviewApi.listReviews.and.callFake(() =>
      fail
        ? throwError(() => new Error('reviews down'))
        : of({ items: pageOne, total: 3, page: 1, per_page: 20, pages: 1 })
    );
    component.load();
    fixture.detectChanges();

    const errorState = el().querySelector('[data-testid="reviews-error"]');
    expect(errorState?.textContent).toContain('reviews down');

    fail = false;
    (errorState?.querySelector('button') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el().querySelector('[data-testid="review-history-list"]')).not.toBeNull();
  });

  it('resolves review → PR → repository and navigates to the PR page', () => {
    component.openPullRequest(pageOne[0]);

    expect(pullRequests.getPullRequestById).toHaveBeenCalledWith('pr-r-1');
    expect(repositories.getRepositoryById).toHaveBeenCalledWith('repo-1');
    expect(navigate).toHaveBeenCalledWith(['/repositories', 'acme', 'api', 'pulls', 482]);
  });

  it('keeps a non-404 resolution failure visible on the row', () => {
    pullRequests.getPullRequestById.and.returnValue(
      throwError(() => new ApiError('PR lookup failed', 500, undefined))
    );
    component.openPullRequest(pageOne[0]);
    fixture.detectChanges();

    expect(component.openErrorId()).toBe('r-1');
    expect(el().querySelector('[data-testid="review-open-error"]')).not.toBeNull();
  });

  it('shows a per-row pending state while the resolution runs', () => {
    // A Subject that never emits keeps the resolution in flight, so the
    // row's pending state is observable (a sync of() would complete it).
    pullRequests.getPullRequestById.and.returnValue(new Subject<PullRequest>().asObservable());
    component.openPullRequest(pageOne[0]);
    expect(component.openingId()).toBe('r-1');
    fixture.detectChanges();
    const button = el().querySelector('[data-testid="review-open-r-1"]') as HTMLButtonElement;
    expect(button.textContent).toContain('Opening…');
    expect((button as HTMLButtonElement).disabled).toBeTrue();
  });
});
