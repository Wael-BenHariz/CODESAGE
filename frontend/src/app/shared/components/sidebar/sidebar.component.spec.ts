import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { SidebarComponent } from './sidebar.component';
import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService, OrgSummary } from '../../../core/services/org-settings.service';
import { User } from '../../../core/models/user.model';

describe('SidebarComponent', () => {
  let fixture: ComponentFixture<SidebarComponent>;
  let auth: {
    currentUser: WritableSignal<User | null>;
    logout: jasmine.Spy;
    switchAccount: jasmine.Spy;
  };
  /** What the (memoized) `GET /orgs` stub answers for the next render. */
  let orgsResult: OrgSummary[];

  const org = (id: string, role: string | null = 'REVIEWER'): OrgSummary => ({
    id,
    name: id,
    account_type: 'Organization',
    role
  });

  const user = (role: string): User => ({
    id: 'u-1',
    login: 'octocat',
    email: 'octo@example.com',
    name: null,
    avatarUrl: 'https://example.com/a.png',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    role
  });

  async function render(userOrNull: User | null): Promise<void> {
    auth.currentUser.set(userOrNull);
    fixture = TestBed.createComponent(SidebarComponent);
    fixture.detectChanges();
    // The sidebar kicks off the org-list fetch fire-and-forget (memoized by
    // AuthContextService) — wait for its promise, then re-render so the
    // org-gated entry reflects the stub.
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function linkTexts(): string[] {
    return Array.from(el().querySelectorAll('.nav-item')).map(a => (a.textContent ?? '').trim());
  }

  beforeEach(() => {
    localStorage.removeItem('codesage_active_org');
    orgsResult = [];
    auth = {
      currentUser: signal<User | null>(null),
      logout: jasmine.createSpy('logout'),
      switchAccount: jasmine.createSpy('switchAccount')
    };
    TestBed.configureTestingModule({
      imports: [SidebarComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: auth },
        { provide: OrgSettingsService, useValue: { listOrgs: () => of(orgsResult) } }
      ]
    });
  });

  afterEach(() => localStorage.removeItem('codesage_active_org'));

  it('shows read-only navigation to a NONE-role user', async () => {
    await render(user('NONE'));

    expect(linkTexts()).toEqual(['Repositories']);
    expect(el().querySelector('[data-testid="nav-org-settings"]')).toBeNull();
    expect(el().querySelector('[data-testid="nav-dashboard"]')).toBeNull();
    expect(el().querySelector('[data-testid="nav-settings"]')).toBeNull();
  });

  it('shows Dashboard and AI model to a write role', async () => {
    await render(user('DEVELOPER'));

    const links = linkTexts();
    expect(links).toContain('Dashboard');
    expect(links).toContain('Repositories');
    expect(links).toContain('AI model');
    expect(links).not.toContain('Organization');
    expect(links).not.toContain('Platform');
  });

  it('adds the Organization entry for an ORG_ADMIN', async () => {
    await render(user('ORG_ADMIN'));

    expect(el().querySelector('[data-testid="nav-org-settings"]')).not.toBeNull();
  });

  it('adds the Platform entry only for a PLATFORM_ADMIN', async () => {
    await render(user('PLATFORM_ADMIN'));
    expect(el().querySelector('[data-testid="nav-platform"]')).not.toBeNull();

    await render(user('ORG_ADMIN'));
    expect(el().querySelector('[data-testid="nav-platform"]')).toBeNull();

    await render(user('DEVELOPER'));
    expect(el().querySelector('[data-testid="nav-platform"]')).toBeNull();
  });

  it('points the brand at the right home per role', async () => {
    await render(user('NONE'));
    expect(el().querySelector('.brand')?.getAttribute('href')).toBe('/repositories');

    await render(user('DEVELOPER'));
    expect(el().querySelector('.brand')?.getAttribute('href')).toBe('/dashboard');
  });

  it('labels the nav landmark for assistive technology', async () => {
    await render(user('DEVELOPER'));
    expect(el().querySelector('nav[aria-label="Main navigation"]')).not.toBeNull();
    expect(el().querySelector('[data-testid="nav-repositories"]')).not.toBeNull();
  });

  // --- Organization Repositories (repo-scoped invitations) --------------------

  it('shows the Organization Repositories entry for an org member', async () => {
    orgsResult = [org('org-alpha')];
    await render(user('REVIEWER'));

    const link = el().querySelector<HTMLAnchorElement>('[data-testid="nav-org-repositories"]');
    expect(link).not.toBeNull();
    expect(link?.getAttribute('href')).toBe('/organization-repositories');
    expect(link?.textContent).toContain('Organization Repositories');
    // Order: directly after Repositories (the personal collection) — every
    // other entry keeps its place.
    expect(linkTexts()).toEqual([
      'Dashboard',
      'Repositories',
      'Organization Repositories',
      'AI model'
    ]);
  });

  it('hides the entry for a role without an org membership', async () => {
    // A REVIEWER with no membership shares nothing — no entry.
    orgsResult = [];
    await render(user('REVIEWER'));
    expect(el().querySelector('[data-testid="nav-org-repositories"]')).toBeNull();
  });

  it('shows the entry for a NONE-role org member — the membership, not the role', async () => {
    // A NONE-role member still has the granted collection (backend decides
    // what is in it) — the entry appears for the membership, not the role.
    orgsResult = [org('org-alpha', 'NONE')];
    await render(user('NONE'));
    expect(el().querySelector('[data-testid="nav-org-repositories"]')).not.toBeNull();
  });

  it('hides the entry while the org list has not loaded', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [SidebarComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: auth },
        {
          provide: OrgSettingsService,
          useValue: { listOrgs: () => throwError(() => new Error('offline')) }
        }
      ]
    });
    await render(user('DEVELOPER'));

    expect(el().querySelector('[data-testid="nav-org-repositories"]')).toBeNull();
  });

  it('keeps the existing Repositories entry pointing at /repositories', async () => {
    orgsResult = [org('org-alpha')];
    await render(user('REVIEWER'));

    const repositories = el().querySelector<HTMLAnchorElement>('[data-testid="nav-repositories"]');
    expect(repositories?.getAttribute('href')).toBe('/repositories');
    expect(repositories?.textContent).toContain('Repositories');
  });
});
