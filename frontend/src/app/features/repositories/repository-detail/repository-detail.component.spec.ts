import { TestBed, ComponentFixture } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { NEVER, Observable, of, throwError } from 'rxjs';

import { RepositoryDetailComponent } from './repository-detail.component';
import { AuthService } from '../../../core/services/auth.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { ToastService } from '../../../core/services/toast.service';
import { OrgSettingsService } from '../../../core/services/org-settings.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { Repository, RepositoryDetail } from '../../../core/models/repository.model';

describe('RepositoryDetailComponent — detail header, tabs and guarded mutations (plan Step 6)', () => {
  let fixture: ComponentFixture<RepositoryDetailComponent>;
  let github: jasmine.SpyObj<RepositoryService>;
  let toast: { success: jasmine.Spy; error: jasmine.Spy };
  let roleSignal: WritableSignal<{ role: string } | null>;

  const repo: Repository = {
    id: 'repo-1',
    name: 'demo',
    fullName: 'acme/demo',
    owner: 'acme',
    description: 'Demo service',
    private: false,
    defaultBranch: 'main',
    language: 'TypeScript',
    stars: 5,
    forks: 2,
    openIssues: 3,
    webhookEnabled: true,
    enabled: true,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-02T00:00:00Z'
  };

  /** GET /repositories/{id}/detail adds stats + the read-only settings block. */
  const detail: RepositoryDetail = {
    ...repo,
    totalPrs: 7,
    totalReviews: 3,
    settings: {
      autoReview: true,
      reviewOnPush: false,
      notifyOnFailure: true,
      maxFilesPerReview: 50
    }
  };

  beforeEach(() => {
    roleSignal = signal({ role: 'DEVELOPER' });
    github = jasmine.createSpyObj<RepositoryService>('RepositoryService', [
      'getRepositoryDetail',
      'updateRepository',
      'enableRepository',
      'disableRepository'
    ]);
    github.getRepositoryDetail.and.returnValue(of(detail));
    github.updateRepository.and.returnValue(of({ ...repo, defaultBranch: 'main' }));
    toast = { success: jasmine.createSpy('success'), error: jasmine.createSpy('error') };

    TestBed.configureTestingModule({
      imports: [RepositoryDetailComponent],
      providers: [
        provideRouter([]), // the component template uses RouterLink
        { provide: RepositoryService, useValue: github },
        { provide: ToastService, useValue: toast },
        // Embedded <app-pr-list> (Pull requests tab).
        {
          provide: PullRequestService,
          useValue: jasmine.createSpyObj<PullRequestService>('PullRequestService', [
            'getPullRequests'
          ])
        },
        { provide: OrgSettingsService, useValue: { listOrgs: () => of([]) } },
        { provide: AuthService, useValue: { currentUser: roleSignal } }
      ]
    });
    (
      TestBed.inject(PullRequestService) as jasmine.SpyObj<PullRequestService>
    ).getPullRequests.and.returnValue(of([]));
  });

  function create(): void {
    fixture = TestBed.createComponent(RepositoryDetailComponent);
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.detectChanges(); // ngOnInit → getRepositoryDetail
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function openSettings(): void {
    (el().querySelector('[data-testid="tab-settings"]') as HTMLButtonElement).click();
    fixture.detectChanges();
  }

  function toggleButton(): HTMLButtonElement {
    return el().querySelector('.toggle-btn') as HTMLButtonElement;
  }

  it('shows the loading state while the request is in flight', () => {
    github.getRepositoryDetail.and.returnValue(NEVER);
    create();

    expect(el().querySelector('[data-testid="repo-loading"]')).not.toBeNull();
    expect(fixture.componentInstance.isLoading()).toBeTrue();
    expect(el().querySelector('[data-testid="repo-load-error"]')).toBeNull();
  });

  it('shows an explicit error state on failure — never a blank content area', () => {
    github.getRepositoryDetail.and.returnValue(
      throwError(() => ({ status: 404, message: 'nope' }))
    );
    create();

    expect(el().querySelector('[data-testid="repo-load-error"]')).not.toBeNull();
    expect(el().textContent).toContain("Couldn't load this repository");
    expect(fixture.componentInstance.loadError()).toBeTrue();
    expect(fixture.componentInstance.repository()).toBeNull();
  });

  it('retries from the error state and renders the repository on success', () => {
    github.getRepositoryDetail.and.returnValue(
      throwError(() => ({ status: 500, message: 'boom' }))
    );
    create();

    github.getRepositoryDetail.and.returnValue(of(detail));
    (el().querySelector('[data-testid="repo-load-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(el().querySelector('[data-testid="repo-load-error"]')).toBeNull();
    expect(el().querySelector('h1')?.textContent).toContain('acme/demo');
    expect(github.getRepositoryDetail).toHaveBeenCalledTimes(2);
  });

  it('renders the detail view: header stats from GET /repositories/{id}/detail', () => {
    create();

    expect(github.getRepositoryDetail).toHaveBeenCalledWith('acme', 'demo');
    expect(el().querySelector('[data-testid="repo-loading"]')).toBeNull();
    expect(el().textContent).toContain('acme/demo');
    expect(el().textContent).toContain('TypeScript');
    expect(el().textContent).toContain('Enabled');
    expect(el().querySelectorAll('.meta-item').length).toBe(7);
    // The two stats only the detail endpoint provides:
    expect(el().textContent).toContain('Pull requests'); // 7
    expect(el().textContent).toContain('Completed reviews'); // 3
  });

  it('renders ARIA tabs: PR list embedded by default, Settings on click', () => {
    create();

    expect(el().querySelector('[data-testid="tab-prs"]')?.getAttribute('aria-selected')).toBe(
      'true'
    );
    expect(el().querySelector('[data-testid="panel-prs"]')).not.toBeNull();
    expect(el().querySelector('[data-testid="panel-prs"] app-pr-list')).not.toBeNull();

    openSettings();

    expect(el().querySelector('[data-testid="panel-settings"]')).not.toBeNull();
    expect(el().querySelector('[data-testid="panel-prs"]')).toBeNull();
    expect(el().querySelector('[data-testid="tab-settings"]')?.getAttribute('aria-selected')).toBe(
      'true'
    );
  });

  it('disables the toggle while pending, blocks a double submit, toasts success', () => {
    let resolveMutation!: () => void;
    const pending$ = new Observable<Repository>(subscriber => {
      resolveMutation = () => {
        subscriber.next(repo);
        subscriber.complete();
      };
    });
    github.disableRepository.and.returnValue(pending$);
    create();
    openSettings();

    toggleButton().click();
    fixture.detectChanges();

    expect(github.disableRepository).toHaveBeenCalledTimes(1);
    expect(toggleButton().disabled).toBeTrue();
    expect(el().textContent).toContain('Saving...');

    // Programmatic second attempt while pending → guard rejects it.
    fixture.componentInstance.toggleEnabled();
    expect(github.disableRepository).toHaveBeenCalledTimes(1);

    resolveMutation();
    fixture.detectChanges();

    expect(toast.success).toHaveBeenCalledWith('Reviews disabled.');
    expect(github.getRepositoryDetail).toHaveBeenCalledTimes(2); // reload on success
    expect(toggleButton().disabled).toBeFalse();
  });

  it('shows a visible error, stays enabled and skips the reload when the toggle fails', () => {
    github.disableRepository.and.returnValue(
      throwError(() => ({ status: 403, message: 'denied' }))
    );
    create();
    openSettings();

    toggleButton().click();
    fixture.detectChanges();

    expect(toast.error).toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(github.getRepositoryDetail).toHaveBeenCalledTimes(1); // no reload on error
    expect(toggleButton().disabled).toBeFalse();
  });

  it('hides the toggle for a read-only (NONE) role', () => {
    roleSignal.set({ role: 'NONE' });
    create();
    openSettings();

    expect(toggleButton()).toBeNull();
  });

  it('saves a changed default branch via PATCH and shows inline success', () => {
    github.updateRepository.and.returnValue(of({ ...repo, defaultBranch: 'develop' }));
    create();
    openSettings();

    const input = el().querySelector('[data-testid="branch-input"]') as HTMLInputElement;
    const save = el().querySelector('[data-testid="branch-save"]') as HTMLButtonElement;
    expect(save.disabled).toBeTrue(); // unchanged draft → no-op

    input.value = 'develop';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(save.disabled).toBeFalse();
    save.click();
    fixture.detectChanges();

    expect(github.updateRepository).toHaveBeenCalledWith('repo-1', {
      default_branch: 'develop'
    });
    expect(fixture.componentInstance.repository()?.defaultBranch).toBe('develop');
    expect(el().textContent).toContain('Default branch saved.');
    expect(el().querySelector('.save-ok')?.getAttribute('role')).toBe('status');
    expect(save.disabled).toBeTrue(); // saved → draft equals the value again
  });

  it('keeps the draft and shows an alert when the PATCH fails', () => {
    github.updateRepository.and.returnValue(throwError(() => ({ status: 422, message: 'bad' })));
    create();
    openSettings();

    const input = el().querySelector('[data-testid="branch-input"]') as HTMLInputElement;
    input.value = 'develop';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    (el().querySelector('[data-testid="branch-save"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(fixture.componentInstance.branchSaving()).toBeFalse();
    expect(fixture.componentInstance.branchDraft()).toBe('develop'); // draft kept
    const err = el().querySelector('.save-err');
    expect(err?.textContent).toContain("Couldn't save the default branch");
    expect(err?.getAttribute('role')).toBe('alert');
    expect(el().textContent).not.toContain('Default branch saved.');
  });

  it('shows the settings block read-only with the explicit note (proposal #17)', () => {
    create();
    openSettings();

    const text = el().textContent ?? '';
    expect(text).toContain('Auto review');
    expect(text).toContain('Max files per review');
    expect(text).toContain("isn't supported by the API yet");
    // Nothing in the read-only block can pretend to save:
    expect(el().querySelectorAll('.settings-readonly input').length).toBe(0);
    expect(el().querySelectorAll('.settings-readonly button').length).toBe(0);
  });
});
