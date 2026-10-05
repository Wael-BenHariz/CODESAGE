import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { DashboardComponent } from './dashboard.component';
import { AuthService } from '../../core/services/auth.service';
import { GithubAppService } from '../../core/services/github-app.service';
import { OrgSettingsService } from '../../core/services/org-settings.service';
import { RepositoryService } from '../../core/services/repository.service';
import { ReviewService } from '../../core/services/review.service';
import { Repository } from '../../core/models/repository.model';
import { ReviewSummary } from '../../core/models/review.model';
import { User } from '../../core/models/user.model';

describe('DashboardComponent — real API data (plan Step 10)', () => {
  let fixture: ComponentFixture<DashboardComponent>;
  let repos: jasmine.SpyObj<RepositoryService>;
  let reviews: jasmine.SpyObj<ReviewService>;
  let role: WritableSignal<User | null>;

  const repo = (name: string, enabled: boolean): Repository => ({
    id: `repo-${name}`,
    name,
    fullName: `acme/${name}`,
    owner: 'acme',
    description: null,
    private: false,
    defaultBranch: 'main',
    language: 'TypeScript',
    stars: 0,
    forks: 0,
    openIssues: 0,
    webhookEnabled: true,
    enabled,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z'
  });

  const review = (id: string, extra: Partial<ReviewSummary> = {}): ReviewSummary => ({
    id,
    pull_request_id: `pr-${id}`,
    user_id: null,
    status: 'completed',
    error_message: null,
    summary: null,
    posting_mode: 'auto',
    posted_at: null,
    edited_summary: null,
    github_review_id: null,
    overall_severity: 'info',
    created_at: '2026-02-01T10:00:00Z',
    completed_at: null,
    ...extra
  });

  const list = (items: ReviewSummary[], total: number, perPage = 5) => ({
    items,
    total,
    page: 1,
    per_page: perPage,
    pages: Math.max(Math.ceil(total / perPage), 1)
  });

  beforeEach(() => {
    role = signal<User | null>({
      id: 'u-1',
      login: 'octocat',
      email: 'octo@example.com',
      name: null,
      avatarUrl: '',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
      role: 'DEVELOPER'
    });

    repos = jasmine.createSpyObj<RepositoryService>('RepositoryService', ['getRepositories']);
    reviews = jasmine.createSpyObj<ReviewService>('ReviewService', ['listReviews']);
    const orgs = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    repos.getRepositories.and.returnValue(of([repo('api', true), repo('web', false)]));
    // Two shapes share listReviews: the recent list (no filter) and the
    // pending count (status_filter='pending').
    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) =>
      statusFilter === 'pending'
        ? of(list([], 7, perPage))
        : of(list([review('rev-1')], 42, perPage))
    );
    orgs.listOrgs.and.returnValue(of([]));

    TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: { currentUser: role } },
        { provide: GithubAppService, useValue: { getInstallStatus: () => of({}) } },
        { provide: RepositoryService, useValue: repos },
        { provide: ReviewService, useValue: reviews },
        // <app-site-header> loads the org switcher through this service.
        { provide: OrgSettingsService, useValue: orgs }
      ]
    });

    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges(); // ngOnInit → loadRepositories + loadReviews (sync of())
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function q(selector: string): HTMLElement | null {
    return el().querySelector(selector);
  }

  function statValues(): string[] {
    return Array.from(el().querySelectorAll('.stat-value')).map(s => (s.textContent ?? '').trim());
  }

  it('derives every stat from real endpoints — no hardcoded values', () => {
    expect(repos.getRepositories).toHaveBeenCalledTimes(1);
    expect(reviews.listReviews).toHaveBeenCalledWith(1, 5);
    expect(reviews.listReviews).toHaveBeenCalledWith(1, 1, 'pending');

    expect(statValues()).toEqual(['2', '1', '42', '7']); // repos, enabled, total, pending
    const labels = Array.from(el().querySelectorAll('.stat-label')).map(l =>
      (l.textContent ?? '').trim()
    );
    expect(labels).toEqual(['Repositories', 'Enabled', 'Reviews', 'Pending']);
    expect(labels).not.toContain('Open PRs'); // the fake card is gone
  });

  it('lists recent reviews with status, severity and time', () => {
    const listEl = q('[data-testid="review-list"]');
    expect(listEl).not.toBeNull();
    expect(listEl?.textContent).toContain('completed');
    expect(listEl?.textContent).toContain('info');
    expect(listEl?.textContent).toContain('Feb 1, 2026');
  });

  it('renders the failed status and backend error verbatim', () => {
    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) =>
      statusFilter === 'pending'
        ? of(list([], 0, perPage))
        : of(list([review('rev-x', { status: 'failed', overall_severity: null })], 1, perPage))
    );
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    const status = q('[data-testid="review-list"] .review-item .review-status');
    expect(status?.classList.contains('failed')).toBeTrue();
    expect(status?.textContent).toContain('failed');
    expect(q('[data-testid="review-list"]')?.textContent).not.toContain('null'); // null severity renders nothing
  });

  it('shows empty states for both sections when nothing exists yet', () => {
    repos.getRepositories.and.returnValue(of([]));
    reviews.listReviews.and.callFake((_page = 1, perPage = 20) => of(list([], 0, perPage)));
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="repos-empty"]')).not.toBeNull();
    expect(q('[data-testid="reviews-empty"]')).not.toBeNull();
    // Loaded-but-zero is a REAL zero (unlike an errored count).
    expect(statValues()).toEqual(['0', '0', '0', '0']);
  });

  it('surfaces a repository load failure with a retry', () => {
    let fail = true;
    repos.getRepositories.and.callFake(() =>
      fail ? throwError(() => new Error('repo boom')) : of([repo('api', true)])
    );
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="repos-error"]')?.textContent).toContain('repo boom');
    expect(statValues()[0]).toBe('—'); // unknown is a dash, never 0

    fail = false;
    (q('[data-testid="repos-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(q('[data-testid="repos-error"]')).toBeNull();
    expect(statValues()[0]).toBe('1');
  });

  it('keeps a reviews failure separate from the repositories section', () => {
    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) =>
      statusFilter === 'pending'
        ? of(list([], 7, perPage))
        : throwError(() => new Error('reviews boom'))
    );
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="reviews-error"]')?.textContent).toContain('reviews boom');
    expect(q('[data-testid="review-list"]')).toBeNull();
    expect(q('[data-testid="repos-error"]')).toBeNull(); // repos untouched
    expect(statValues()).toEqual(['2', '1', '—', '7']);
  });

  it('a failed pending count shows a dash — never a fake 0', () => {
    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) =>
      statusFilter === 'pending'
        ? throwError(() => new Error('count boom'))
        : of(list([review('rev-1')], 42, perPage))
    );
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="stat-pending"]')?.textContent?.trim()).toBe('—');
    // The recent list still renders — the two calls fail independently.
    expect(q('[data-testid="review-list"]')).not.toBeNull();
    expect(q('[data-testid="stat-reviews"]')?.textContent?.trim()).toBe('42');
  });
});
