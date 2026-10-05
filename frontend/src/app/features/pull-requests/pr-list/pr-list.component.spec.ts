import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NEVER, of, throwError } from 'rxjs';

import { PrListComponent } from './pr-list.component';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService } from '../../../core/services/org-settings.service';
import { PullRequest } from '../../../core/models/pull-request.model';

describe('PrListComponent — four states + call contract (plan Step 2)', () => {
  let fixture: ComponentFixture<PrListComponent>;
  let github: jasmine.SpyObj<PullRequestService>;

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
    github = jasmine.createSpyObj<PullRequestService>('PullRequestService', ['getPullRequests']);

    TestBed.configureTestingModule({
      imports: [PrListComponent],
      providers: [
        provideRouter([]), // the component template uses RouterLink
        { provide: PullRequestService, useValue: github },
        // <app-site-header> → AuthContextService (no session in tests).
        { provide: AuthService, useValue: { currentUser: () => null } },
        { provide: OrgSettingsService, useValue: { listOrgs: () => of([]) } }
      ]
    });
  });

  function create(): void {
    fixture = TestBed.createComponent(PrListComponent);
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.detectChanges(); // ngOnInit → getPullRequests (sync of()/throwError)
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('shows an explicit error state on failure, not "No pull requests found"', () => {
    github.getPullRequests.and.returnValue(
      throwError(() => ({ status: 404, message: 'not found' }))
    );
    create();

    expect(el().querySelector('[data-testid="pr-list-load-error"]')).not.toBeNull();
    expect(el().textContent).not.toContain('No pull requests found');
    expect(fixture.componentInstance.loadError()).toBeTrue();
  });

  it('shows the empty state only when the load succeeded with no results', () => {
    github.getPullRequests.and.returnValue(of([]));
    create();

    expect(el().querySelector('[data-testid="pr-list-load-error"]')).toBeNull();
    expect(el().textContent).toContain('No pull requests found');
    expect(fixture.componentInstance.loadError()).toBeFalse();
  });

  it('retries the load from the error state', () => {
    github.getPullRequests.and.returnValue(throwError(() => ({ status: 500, message: 'boom' })));
    create();

    github.getPullRequests.and.returnValue(of([pr]));
    (el().querySelector('[data-testid="pr-list-load-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges(); // the retry is synchronous; refresh the DOM

    expect(fixture.componentInstance.loadError()).toBeFalse();
    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(github.getPullRequests).toHaveBeenCalledTimes(2);
  });

  // --- four-state coverage (plan Step 2) ------------------------------------

  it('shows the loading state while the request is in flight', () => {
    github.getPullRequests.and.returnValue(NEVER);
    create();

    expect(el().querySelector('[data-testid="pr-list-loading"]')).not.toBeNull();
    expect(fixture.componentInstance.isLoading()).toBeTrue();
    expect(el().querySelector('[data-testid="pr-list-load-error"]')).toBeNull();
    expect(el().textContent).not.toContain('No pull requests found');
  });

  it('renders the PR rows from the mapped model on success', () => {
    github.getPullRequests.and.returnValue(of([pr]));
    create();

    expect(el().querySelector('[data-testid="pr-list-loading"]')).toBeNull();
    expect(fixture.componentInstance.isLoading()).toBeFalse();
    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(el().querySelector('.pr-title')?.textContent).toContain('Fix the thing');
    expect(el().textContent).toContain('#7');
    expect(el().textContent).toContain('by octocat');
  });

  it('passes the owner and repo as separate args (phantom combined path removed)', () => {
    github.getPullRequests.and.returnValue(of([pr]));
    create();

    expect(github.getPullRequests).toHaveBeenCalledWith('acme', 'demo');
  });
});
