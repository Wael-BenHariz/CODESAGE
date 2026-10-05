import { TestBed, ComponentFixture } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { NEVER, Observable, of, throwError } from 'rxjs';

import { RepositoryDetailComponent } from './repository-detail.component';
import { AuthService } from '../../../core/services/auth.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { ToastService } from '../../../core/services/toast.service';
import { OrgSettingsService } from '../../../core/services/org-settings.service';
import { Repository } from '../../../core/models/repository.model';

describe('RepositoryDetailComponent — four states + guarded toggle (plan Step 2)', () => {
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

  beforeEach(() => {
    roleSignal = signal({ role: 'DEVELOPER' });
    github = jasmine.createSpyObj<RepositoryService>('RepositoryService', [
      'getRepository',
      'enableRepository',
      'disableRepository'
    ]);
    toast = { success: jasmine.createSpy('success'), error: jasmine.createSpy('error') };

    TestBed.configureTestingModule({
      imports: [RepositoryDetailComponent],
      providers: [
        provideRouter([]), // the component template uses RouterLink
        { provide: RepositoryService, useValue: github },
        { provide: ToastService, useValue: toast },
        // <app-site-header> → AuthContextService (no session in tests).
        { provide: OrgSettingsService, useValue: { listOrgs: () => of([]) } },
        { provide: AuthService, useValue: { currentUser: roleSignal } }
      ]
    });
  });

  function create(): void {
    fixture = TestBed.createComponent(RepositoryDetailComponent);
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.detectChanges(); // ngOnInit → getRepository
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function toggleButton(): HTMLButtonElement {
    return el().querySelector('.toggle-btn') as HTMLButtonElement;
  }

  it('shows the loading state while the request is in flight', () => {
    github.getRepository.and.returnValue(NEVER);
    create();

    expect(el().querySelector('[data-testid="repo-loading"]')).not.toBeNull();
    expect(fixture.componentInstance.isLoading()).toBeTrue();
    expect(el().querySelector('[data-testid="repo-load-error"]')).toBeNull();
  });

  it('shows an explicit error state on failure — never a blank content area', () => {
    github.getRepository.and.returnValue(throwError(() => ({ status: 404, message: 'nope' })));
    create();

    expect(el().querySelector('[data-testid="repo-load-error"]')).not.toBeNull();
    expect(el().textContent).toContain("Couldn't load this repository");
    expect(fixture.componentInstance.loadError()).toBeTrue();
    expect(fixture.componentInstance.repository()).toBeNull();
  });

  it('retries from the error state and renders the repository on success', () => {
    github.getRepository.and.returnValue(throwError(() => ({ status: 500, message: 'boom' })));
    create();

    github.getRepository.and.returnValue(of(repo));
    (el().querySelector('[data-testid="repo-load-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(el().querySelector('[data-testid="repo-load-error"]')).toBeNull();
    expect(el().querySelector('h1')?.textContent).toContain('acme/demo');
    expect(github.getRepository).toHaveBeenCalledTimes(2);
  });

  it('renders the repository from the mapped model (owner/repo as separate args)', () => {
    github.getRepository.and.returnValue(of(repo));
    create();

    expect(github.getRepository).toHaveBeenCalledWith('acme', 'demo');
    expect(el().querySelector('[data-testid="repo-loading"]')).toBeNull();
    expect(el().querySelector('[data-testid="repo-load-error"]')).toBeNull();
    expect(el().textContent).toContain('acme/demo');
    expect(el().textContent).toContain('TypeScript');
    expect(el().textContent).toContain('Enabled');
    expect(el().querySelectorAll('.meta-item').length).toBe(6);
  });

  it('disables the toggle while pending, blocks a double submit, toasts success', () => {
    let resolveMutation!: () => void;
    const pending$ = new Observable<Repository>(subscriber => {
      resolveMutation = () => {
        subscriber.next(repo);
        subscriber.complete();
      };
    });
    github.getRepository.and.returnValue(of(repo));
    github.disableRepository.and.returnValue(pending$);
    create();

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
    expect(github.getRepository).toHaveBeenCalledTimes(2); // reload on success
    expect(toggleButton().disabled).toBeFalse();
  });

  it('shows a visible error, stays enabled and skips the reload when the toggle fails', () => {
    github.getRepository.and.returnValue(of(repo));
    github.disableRepository.and.returnValue(
      throwError(() => ({ status: 403, message: 'denied' }))
    );
    create();

    toggleButton().click();
    fixture.detectChanges();

    expect(toast.error).toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(github.getRepository).toHaveBeenCalledTimes(1); // no reload on error
    expect(toggleButton().disabled).toBeFalse();
  });
});
