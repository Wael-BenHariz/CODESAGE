import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { DashboardComponent } from './dashboard.component';
import { AuthService } from '../../core/services/auth.service';
import { GithubAppService } from '../../core/services/github-app.service';
import { LlmSettingsService } from '../../core/services/llm-settings.service';
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
  let github: jasmine.SpyObj<GithubAppService>;
  let llm: jasmine.SpyObj<LlmSettingsService>;
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
    started_at: '2026-02-01T09:59:00Z',
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
    github = jasmine.createSpyObj<GithubAppService>('GithubAppService', ['getInstallStatus']);
    llm = jasmine.createSpyObj<LlmSettingsService>('LlmSettingsService', ['getLLMSettings']);
    const orgs = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    repos.getRepositories.and.returnValue(of([repo('api', true), repo('web', false)]));
    // Six shapes share listReviews: the recent list (per_page=5), the
    // severity window (per_page=100) and the four status_filter counts.
    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) => {
      if (statusFilter === 'pending') return of(list([], 7, perPage));
      if (statusFilter === 'completed') return of(list([], 30, perPage));
      if (statusFilter === 'failed') return of(list([], 5, perPage));
      if (statusFilter === 'ready_to_post') return of(list([], 3, perPage));
      if (perPage === 100) {
        return of(
          list([review('rev-1'), review('rev-2', { overall_severity: 'warning' })], 42, perPage)
        );
      }
      return of(list([review('rev-1')], 42, perPage));
    });
    github.getInstallStatus.and.returnValue(of({ installed: true, installation_id: 1 }));
    llm.getLLMSettings.and.returnValue(
      of({ hasApiKey: true, isUsingDefault: false, provider: null, model: null, baseUrl: null })
    );
    orgs.listOrgs.and.returnValue(of([]));

    TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: { currentUser: role } },
        { provide: GithubAppService, useValue: github },
        { provide: LlmSettingsService, useValue: llm },
        { provide: RepositoryService, useValue: repos },
        { provide: ReviewService, useValue: reviews },
        // The setup checklist loads the org list for the posting-mode row.
        { provide: OrgSettingsService, useValue: orgs }
      ]
    });

    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges(); // ngOnInit → all loads (sync of())
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
    expect(reviews.listReviews).toHaveBeenCalledWith(1, 1, 'completed');
    expect(reviews.listReviews).toHaveBeenCalledWith(1, 1, 'failed');
    expect(reviews.listReviews).toHaveBeenCalledWith(1, 1, 'ready_to_post');
    expect(reviews.listReviews).toHaveBeenCalledWith(1, 100);

    expect(statValues()).toEqual(['2', '1', '42', '7', '30', '5', '3']); // repos…awaiting
    const labels = Array.from(el().querySelectorAll('.stat-label')).map(l =>
      (l.textContent ?? '').trim()
    );
    expect(labels).toEqual([
      'Repositories',
      'Enabled',
      'Reviews',
      'Pending',
      'Completed',
      'Failed',
      'Awaiting approval'
    ]);
    expect(labels).not.toContain('Open PRs'); // the fake card is gone
  });

  it('lists recent reviews with status, severity and time', () => {
    const listEl = q('[data-testid="review-list"]');
    expect(listEl).not.toBeNull();
    expect(listEl?.textContent).toContain('completed');
    expect(listEl?.textContent).toContain('info');
    // Relative time in the row, the absolute timestamp in title/datetime.
    const time = q('[data-testid="review-list"] time.review-time');
    expect(time?.textContent).toMatch(/ago|just now/);
    expect(time?.getAttribute('title')).toContain('Feb 1, 2026');
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
    expect(q('[data-testid="severity-empty"]')).not.toBeNull();
    // Loaded-but-zero is a REAL zero (unlike an errored count).
    expect(statValues()).toEqual(['0', '0', '0', '0', '0', '0', '0']);
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
    expect(statValues()).toEqual(['2', '1', '—', '7', '—', '—', '—']);
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

  it('setup checklist: visible while incomplete, hidden once every known row is done', () => {
    // Base mocks: GitHub installed, one repo enabled, LLM key saved → hidden.
    expect(q('[data-testid="setup-checklist"]')).toBeNull();

    github.getInstallStatus.and.returnValue(of({ installed: false, installation_id: null }));
    llm.getLLMSettings.and.returnValue(
      of({ hasApiKey: false, isUsingDefault: true, provider: null, model: null, baseUrl: null })
    );
    repos.getRepositories.and.returnValue(of([repo('api', false)])); // nothing enabled
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="setup-checklist"]')).not.toBeNull();
    expect(q('[data-testid="check-github"]')?.textContent).toContain('Install the GitHub App');
    expect(q('[data-testid="check-repos"]')?.textContent).toContain('Connect a repository');
    expect(q('[data-testid="check-llm"]')?.textContent).toContain('Add your AI model key');
    expect(q('[data-testid="check-llm"]')?.textContent).toContain('platform default');
    // No posting-mode row for non-org-admins.
    expect(q('[data-testid="check-posting"]')).toBeNull();
  });

  it('omits checklist rows whose source failed to load — unknown is not incomplete', () => {
    github.getInstallStatus.and.returnValue(throwError(() => new Error('status boom')));
    llm.getLLMSettings.and.returnValue(throwError(() => new Error('llm boom')));
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="check-github"]')).toBeNull();
    expect(q('[data-testid="check-llm"]')).toBeNull();
    // The only known row (repos, enabled) is done → the checklist hides.
    expect(q('[data-testid="setup-checklist"]')).toBeNull();
  });

  it('charts the severity distribution from the recent window, labelled and Q1-mapped', () => {
    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) => {
      if (statusFilter) return of(list([], 0, perPage));
      if (perPage === 100) {
        return of(
          list(
            [
              review('s1', { overall_severity: 'error' }),
              review('s2', { overall_severity: 'error' }),
              review('s3', { overall_severity: 'warning' }),
              review('s4', { overall_severity: 'info' })
            ],
            4,
            perPage
          )
        );
      }
      return of(list([review('rev-1')], 42, perPage));
    });
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="severity-chart"]')).not.toBeNull();
    const rows = Array.from(el().querySelectorAll('.sev-row')).map(r =>
      (r.textContent ?? '').replace(/\s+/g, ' ').trim()
    );
    // error → critical (Q1 vocab mapping), warning → medium.
    expect(rows[0]).toContain('critical');
    expect(rows[0]).toContain('2 reviews (50%)');
    expect(rows[2]).toContain('medium');
    expect(rows[2]).toContain('1 review (25%)');
    expect(rows[4]).toContain('info');
    // The window is always stated — never implied to be "all reviews".
    expect(q('.section-note')?.textContent).toContain('Most recent 4 reviews (max 100)');
  });

  it('recovers the severity section independently via its own retry', () => {
    let fail = true;
    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) => {
      if (statusFilter) return of(list([], 0, perPage));
      if (perPage === 100 && fail) return throwError(() => new Error('sev boom'));
      return of(list([review('rev-1')], 42, perPage));
    });
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    expect(q('[data-testid="severity-error"]')?.textContent).toContain('sev boom');
    fail = false;
    (q('[data-testid="severity-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(q('[data-testid="severity-error"]')).toBeNull();
    expect(q('[data-testid="severity-chart"]')).not.toBeNull();
  });

  it('summarises staged reviews in an awaiting-approval callout', () => {
    // Base mock: status_filter=ready_to_post → total 3.
    const callout = q('[data-testid="awaiting-approval"]');
    expect(callout).not.toBeNull();
    expect(callout?.textContent).toContain('3');
    expect(callout?.textContent).toContain('reviews are waiting for approval');

    reviews.listReviews.and.callFake((_page = 1, perPage = 20, statusFilter?: string) =>
      statusFilter === 'ready_to_post'
        ? of(list([], 0, perPage))
        : of(list([review('rev-1')], 42, perPage))
    );
    fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();
    expect(q('[data-testid="awaiting-approval"]')).toBeNull();
  });
});
