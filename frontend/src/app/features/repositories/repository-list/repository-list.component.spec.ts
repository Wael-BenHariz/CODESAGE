import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { NEVER, of, throwError } from 'rxjs';

import { RepositoryListComponent } from './repository-list.component';
import { AuthService } from '../../../core/services/auth.service';
import { GithubAppService } from '../../../core/services/github-app.service';
import { OrgSettingsService } from '../../../core/services/org-settings.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { GitHubAppRepo } from '../../../core/models/github-app.model';
import { Repository } from '../../../core/models/repository.model';
import { User } from '../../../core/models/user.model';

/**
 * The install CTA (window.location.href) and Remove (window.confirm) are
 * render-asserted only — firing them would navigate or block the Karma
 * runner page (same class of hazard as the documented beforeunload rule).
 */
describe('RepositoryListComponent — grid, filters and connect modal', () => {
  let fixture: ComponentFixture<RepositoryListComponent>;
  let component: RepositoryListComponent;
  let repos: jasmine.SpyObj<RepositoryService>;
  let installed: WritableSignal<boolean>;
  let github: {
    githubInstalled: WritableSignal<boolean>;
    getInstallStatus: jasmine.Spy;
    getAppRepos: jasmine.Spy;
    saveRepoSelection: jasmine.Spy;
  };
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

  const appRepo = (id: number, name: string, enabled: boolean): GitHubAppRepo => ({
    id,
    name,
    private: false,
    enabled
  });

  beforeEach(() => {
    installed = signal(true);
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

    repos = jasmine.createSpyObj<RepositoryService>('RepositoryService', [
      'getRepositories',
      'enableRepository',
      'disableRepository',
      'deleteRepository'
    ]);
    repos.getRepositories.and.returnValue(of([repo('api', true), repo('web', false)]));
    repos.enableRepository.and.callFake((id: string) => of(repo(id, true)));
    repos.disableRepository.and.callFake((id: string) => of(repo(id, false)));

    github = {
      githubInstalled: installed,
      getInstallStatus: jasmine
        .createSpy('getInstallStatus')
        .and.callFake(() =>
          of({ installed: installed(), installation_id: installed() ? 1 : null })
        ),
      getAppRepos: jasmine
        .createSpy('getAppRepos')
        .and.returnValue(of([appRepo(1, 'acme/api', false), appRepo(2, 'acme/web', true)])),
      saveRepoSelection: jasmine.createSpy('saveRepoSelection').and.returnValue(of({ saved: true }))
    };

    TestBed.configureTestingModule({
      imports: [RepositoryListComponent],
      providers: [
        provideRouter([]),
        {
          provide: AuthService,
          useValue: { currentUser: role, getInstallUrl: jasmine.createSpy('getInstallUrl') }
        },
        { provide: GithubAppService, useValue: github },
        { provide: RepositoryService, useValue: repos },
        // <app-site-header> loads the org switcher through this service.
        {
          provide: OrgSettingsService,
          useValue: jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs'])
        }
      ]
    });
    (
      TestBed.inject(OrgSettingsService) as jasmine.SpyObj<OrgSettingsService>
    ).listOrgs.and.returnValue(of([]));

    fixture = TestBed.createComponent(RepositoryListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges(); // ngOnInit → loadRepositories + install status (sync of())
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders the grid with enabled/disabled counts', () => {
    expect(component.isLoading()).toBeFalse();
    expect(el().querySelectorAll('.repo-card').length).toBe(2);
    expect(el().querySelectorAll('.filter-btn').length).toBe(3);
    expect(component.openCount).toBe(1);
    expect(component.disabledCount).toBe(1);
    expect(el().textContent).toContain('acme/api');
  });

  it('filters the grid to enabled or disabled rows', () => {
    const buttons = Array.from(el().querySelectorAll('.filter-btn')) as HTMLButtonElement[];

    buttons[1].click(); // Enabled
    fixture.detectChanges();
    expect(component.filteredRepos.map(r => r.enabled)).toEqual([true]);
    expect(el().querySelectorAll('.repo-card').length).toBe(1);

    buttons[2].click(); // Disabled
    fixture.detectChanges();
    expect(component.filteredRepos.map(r => r.enabled)).toEqual([false]);

    buttons[0].click(); // All
    fixture.detectChanges();
    expect(el().querySelectorAll('.repo-card').length).toBe(2);
  });

  it('keeps showing the loading state until the list resolves', () => {
    repos.getRepositories.and.returnValue(NEVER);
    fixture = TestBed.createComponent(RepositoryListComponent);
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Loading repositories...');
  });

  it('enables a disabled repo and reloads the list', () => {
    component.toggleRepo(repo('web', false));

    expect(repos.enableRepository).toHaveBeenCalledWith('repo-web');
    expect(repos.getRepositories).toHaveBeenCalledTimes(2); // post-action refresh
  });

  it('disables an enabled repo', () => {
    component.toggleRepo(repo('api', true));

    expect(repos.disableRepository).toHaveBeenCalledWith('repo-api');
    expect(repos.getRepositories).toHaveBeenCalledTimes(2);
  });

  it('shows the connect CTA when the App is installed but no repo exists', () => {
    repos.getRepositories.and.returnValue(of([]));
    fixture = TestBed.createComponent(RepositoryListComponent);
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('No repositories connected yet');
    expect(text).toContain('+ Select Repositories');
    expect(text).not.toContain('Install GitHub App');
  });

  it('shows the install CTA when the App is not installed', () => {
    installed.set(false);
    repos.getRepositories.and.returnValue(of([]));
    fixture = TestBed.createComponent(RepositoryListComponent);
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('No repositories connected yet');
    expect(text).toContain('Install GitHub App'); // render-only: never clicked here
  });

  it('hides every write action for a read-only (NONE) role', () => {
    role.set({ ...role()!, role: 'NONE' });
    fixture = TestBed.createComponent(RepositoryListComponent);
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('acme/api'); // reads still render
    expect(text).not.toContain('+ Connect'); // header action
    expect(text).not.toContain('Remove'); // per-card action
    expect(el().querySelectorAll('.repo-card .btn-ghost').length).toBe(0); // no toggles
  });

  it('opens the modal, loads App repos and saves a flipped selection', () => {
    component.openConnectModal();
    fixture.detectChanges();

    expect(component.showConnectModal()).toBeTrue();
    // once on init (pending-selection note) + once for the modal list
    expect(github.getAppRepos).toHaveBeenCalledTimes(2);
    expect(el().querySelectorAll('.modal').length).toBe(1);

    component.toggleSelection(appRepo(1, 'acme/api', false));
    fixture.detectChanges();

    expect(github.saveRepoSelection).toHaveBeenCalledWith([
      { id: 1, name: 'acme/api', private: false, enabled: true }, // flipped
      { id: 2, name: 'acme/web', private: false, enabled: true } // untouched
    ]);
    expect(component.connectingRepo()).toBeNull();
    expect(component.saveError()).toBeNull();
  });

  it('surfaces an inline save error when the selection fails', () => {
    github.saveRepoSelection.and.returnValue(throwError(() => new Error('nope')));
    component.openConnectModal();
    fixture.detectChanges();

    component.toggleSelection(appRepo(1, 'acme/api', false));
    fixture.detectChanges();

    expect(component.saveError()).toBe('Could not save your selection. Please try again.');
    expect(component.connectingRepo()).toBeNull();
    expect(el().querySelector('.save-error')?.textContent).toContain(
      'Could not save your selection'
    );
  });

  it('shows a retry when the modal list fails to load (non-400)', () => {
    github.getAppRepos.and.returnValue(throwError(() => ({ status: 500 })));

    component.openConnectModal();
    fixture.detectChanges();

    expect(component.modalError()).toBe('Could not load repositories. Please try again.');
    expect(el().textContent).toContain('Retry');
  });

  it('treats a 400 as "App not installed" — install branch, no error banner', () => {
    installed.set(false);
    github.getAppRepos.and.returnValue(throwError(() => ({ status: 400 })));

    component.openConnectModal();
    fixture.detectChanges();

    expect(component.modalError()).toBeNull();
    expect(el().textContent).toContain('Install GitHub App'); // render-only
  });
});
