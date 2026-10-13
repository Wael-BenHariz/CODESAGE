import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NEVER, of, throwError } from 'rxjs';

import { OrganizationRepositoriesComponent } from './organization-repositories.component';
import { ApiError } from '../../../core/services/api.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { Repository } from '../../../core/models/repository.model';

function makeRepo(
  id: string,
  fullName: string,
  orgId: string | null,
  orgName: string | null,
  extra: Partial<Repository> = {}
): Repository {
  const [owner = '', name = ''] = fullName.split('/');
  return {
    id,
    name,
    fullName,
    owner,
    description: null,
    private: false,
    defaultBranch: 'main',
    language: null,
    stars: 0,
    forks: 0,
    openIssues: 0,
    webhookEnabled: false,
    enabled: true,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    orgId,
    orgName,
    ...extra
  };
}

describe('OrganizationRepositoriesComponent (repo-scoped invitations)', () => {
  let fixture: ComponentFixture<OrganizationRepositoriesComponent>;
  let component: OrganizationRepositoriesComponent;
  let repos: jasmine.SpyObj<RepositoryService>;

  /** Two orgs, three granted repositories — the multi-org reviewer case. */
  const grantedRows: Repository[] = [
    makeRepo('r-api', 'alpha/api', 'org-alpha', 'alpha', { enabled: true }),
    makeRepo('r-web', 'alpha/web', 'org-alpha', 'alpha', { enabled: false }),
    makeRepo('r-beta', 'beta/service', 'org-beta', 'beta', {
      description: 'Beta service'
    })
  ];

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function q(testId: string): HTMLElement | null {
    return el().querySelector(`[data-testid="${testId}"]`);
  }

  beforeEach(() => {
    repos = jasmine.createSpyObj<RepositoryService>('RepositoryService', [
      'getOrganizationRepositories',
      'getRepositories'
    ]);
    repos.getOrganizationRepositories.and.returnValue(of(grantedRows));

    TestBed.configureTestingModule({
      imports: [OrganizationRepositoriesComponent],
      providers: [provideRouter([]), { provide: RepositoryService, useValue: repos }]
    });

    fixture = TestBed.createComponent(OrganizationRepositoriesComponent);
    component = fixture.componentInstance;
  });

  it('requests the server-side organization collection, never the union', () => {
    fixture.detectChanges();

    expect(repos.getOrganizationRepositories).toHaveBeenCalledTimes(1);
    // The unfiltered call would return personal repositories too — the page
    // must never fall back to it.
    expect(repos.getRepositories).not.toHaveBeenCalled();
  });

  it('renders exactly the granted repositories with org attribution', () => {
    fixture.detectChanges();

    const cards = el().querySelectorAll('[data-testid="org-repo-card"]');
    expect(cards.length).toBe(3);
    expect(el().textContent).toContain('alpha/api');
    expect(el().textContent).toContain('alpha/web');
    expect(el().textContent).toContain('beta/service');
    // Nothing ungranted can appear — the stubbed source IS the grant list.
    expect(el().textContent).not.toContain('alpha/infrastructure');

    const first = cards[0];
    expect(first.querySelector('.repo-name')?.getAttribute('href')).toBe('/repositories/alpha/api');
    const prs = first.querySelector<HTMLAnchorElement>('.repo-actions a.btn');
    expect(prs?.getAttribute('href')).toBe('/repositories/alpha/api/pulls');
    expect(first.querySelector('[data-testid="org-repo-org"]')?.textContent).toContain('alpha');
  });

  it('shows the loading state first — no repository flashes before the scoped data', () => {
    repos.getOrganizationRepositories.and.returnValue(NEVER);
    fixture.detectChanges();

    expect(q('org-repos-loading')).not.toBeNull();
    expect(q('org-repos-grid')).toBeNull();
    expect(q('org-repos-empty')).toBeNull();
  });

  it('renders the empty state for a reviewer without grants (no org-wide fallback)', () => {
    repos.getOrganizationRepositories.and.returnValue(of([]));
    fixture.detectChanges();

    expect(q('org-repos-empty')).not.toBeNull();
    expect(q('org-repos-empty')?.textContent).toContain(
      'No organization repositories have been shared with you yet.'
    );
    expect(q('org-repos-grid')).toBeNull();
  });

  it('renders the error state and retries the same scoped request', () => {
    repos.getOrganizationRepositories.and.returnValue(
      throwError(() => new ApiError('boom', 500, undefined))
    );
    fixture.detectChanges();

    expect(q('org-repos-error')).not.toBeNull();
    expect(q('org-repos-error')?.textContent).toContain('boom');
    expect(component.state()).toBe('error');

    repos.getOrganizationRepositories.and.returnValue(of(grantedRows));
    (q('org-repos-error')?.querySelector('button') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(repos.getOrganizationRepositories).toHaveBeenCalledTimes(2);
    expect(q('org-repos-grid')).not.toBeNull();
    expect(el().querySelectorAll('[data-testid="org-repo-card"]').length).toBe(3);
  });

  it('offers an organization filter for multi-org users and scopes the grid', () => {
    fixture.detectChanges();

    const filter = q('org-repos-filter') as HTMLSelectElement | null;
    expect(filter).not.toBeNull();
    // All organizations + one option per org present in the granted rows.
    expect(filter?.options.length).toBe(3);
    expect(filter?.options[1].textContent).toContain('alpha');
    expect(filter?.options[2].textContent).toContain('beta');

    filter!.value = 'org-beta';
    filter!.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    const names = Array.from(el().querySelectorAll('[data-testid="org-repo-card"] .repo-name')).map(
      node => (node.textContent ?? '').trim()
    );
    expect(names).toEqual(['beta/service']);
  });

  it('keeps a single-org user filter-free (no needless selector)', () => {
    repos.getOrganizationRepositories.and.returnValue(
      of([makeRepo('r-api', 'alpha/api', 'org-alpha', 'alpha')])
    );
    fixture.detectChanges();

    expect(q('org-repos-filter')).toBeNull();
    expect(el().querySelectorAll('[data-testid="org-repo-card"]').length).toBe(1);
  });

  it('resets a stale organization filter when the data changes', () => {
    fixture.detectChanges();
    component.setOrgFilter('org-beta');
    fixture.detectChanges();

    // Next visit (e.g. after accepting another invitation) has no more
    // beta rows — the filter falls back to all organizations.
    repos.getOrganizationRepositories.and.returnValue(
      of([makeRepo('r-api', 'alpha/api', 'org-alpha', 'alpha')])
    );
    component.load();
    fixture.detectChanges();

    expect(component.orgFilter()).toBe('all');
    expect(el().querySelectorAll('[data-testid="org-repo-card"]').length).toBe(1);
  });

  it('refetches on every visit — a fresh load after invitation acceptance', () => {
    fixture.detectChanges();

    // A second component lifecycle (login restore / route revisit) asks the
    // server again instead of reusing stale in-memory state.
    const second = TestBed.createComponent(OrganizationRepositoriesComponent);
    second.detectChanges();

    expect(repos.getOrganizationRepositories).toHaveBeenCalledTimes(2);
  });
});
