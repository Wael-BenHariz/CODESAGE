import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';

import { SiteHeaderComponent } from './site-header.component';
import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService, OrgSummary } from '../../../core/services/org-settings.service';
import { User } from '../../../core/models/user.model';

describe('SiteHeaderComponent', () => {
  let fixture: ComponentFixture<SiteHeaderComponent>;
  let auth: {
    currentUser: WritableSignal<User | null>;
    logout: jasmine.Spy;
    switchAccount: jasmine.Spy;
  };
  let orgSvc: jasmine.SpyObj<OrgSettingsService>;

  const org = (id: string, role: string, name = id): OrgSummary => ({
    id,
    name,
    account_type: 'Organization',
    role
  });

  const user = (role: string, avatarUrl = 'https://example.com/a.png'): User => ({
    id: 'u-1',
    login: 'octocat',
    email: 'octo@example.com',
    name: null,
    avatarUrl,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    role
  });

  function setOrgs(orgs: Observable<OrgSummary[]>): void {
    orgSvc.listOrgs.and.returnValue(orgs);
  }

  function render(role: string | null): void {
    auth.currentUser.set(role ? user(role) : null);
    fixture = TestBed.createComponent(SiteHeaderComponent);
    fixture.detectChanges();
  }

  beforeEach(() => {
    localStorage.removeItem('codesage_active_org');
    auth = {
      currentUser: signal<User | null>(null),
      logout: jasmine.createSpy('logout'),
      switchAccount: jasmine.createSpy('switchAccount')
    };
    orgSvc = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    setOrgs(of([]));

    TestBed.configureTestingModule({
      imports: [SiteHeaderComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: auth },
        { provide: OrgSettingsService, useValue: orgSvc }
      ]
    });
  });

  afterEach(() => {
    localStorage.removeItem('codesage_active_org');
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function linkTexts(): string[] {
    return Array.from(el().querySelectorAll('.nav-link')).map(a => (a.textContent ?? '').trim());
  }

  it('shows read-only navigation to a NONE-role user', () => {
    render('NONE');

    expect(linkTexts()).toEqual(['Repositories']);
    expect(el().querySelector('[data-testid="nav-org-settings"]')).toBeNull();
  });

  it('shows Dashboard and Settings to a write role', () => {
    render('DEVELOPER');

    const links = linkTexts();
    expect(links).toContain('Dashboard');
    expect(links).toContain('Repositories');
    expect(links).toContain('Settings');
    expect(links).not.toContain('Organization');
  });

  it('adds the Organization entry for an ORG_ADMIN', () => {
    render('ORG_ADMIN');

    expect(el().querySelector('[data-testid="nav-org-settings"]')).not.toBeNull();
  });

  it('adds the Platform entry only for a PLATFORM_ADMIN (plan Step 9)', () => {
    render('PLATFORM_ADMIN');
    expect(el().querySelector('[data-testid="nav-platform"]')).not.toBeNull();

    render('ORG_ADMIN');
    expect(el().querySelector('[data-testid="nav-platform"]')).toBeNull();

    render('DEVELOPER');
    expect(el().querySelector('[data-testid="nav-platform"]')).toBeNull();
  });

  it('does not render the user menu without a session profile', () => {
    render(null);

    expect(el().querySelector('.user-menu')).toBeNull();
    expect(el().querySelector('[data-testid="site-header"]')).not.toBeNull();
  });

  it('logs out and switches account through AuthService', () => {
    render('DEVELOPER');

    const buttons = Array.from(el().querySelectorAll('button'));
    buttons.find(b => b.textContent?.includes('Logout'))?.click();
    buttons.find(b => b.textContent?.includes('Switch Account'))?.click();

    expect(auth.logout).toHaveBeenCalledTimes(1);
    expect(auth.switchAccount).toHaveBeenCalledTimes(1);
  });

  it('renders the avatar only when the profile carries one', () => {
    render('DEVELOPER');
    expect(el().querySelector('.user-avatar')).not.toBeNull();

    auth.currentUser.set({ ...user('DEVELOPER', '') });
    fixture.detectChanges();
    expect(el().querySelector('.user-avatar')).toBeNull();
  });

  /**
   * `ensureOrgs()` resolves through a promise (firstValueFrom), so the orgs
   * signal updates in a microtask — flush it before asserting DOM that
   * depends on the loaded list.
   */
  async function flushOrgs(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  it('hides the org switcher for a single org', async () => {
    setOrgs(of([org('only', 'ORG_ADMIN', 'single')]));
    render('ORG_ADMIN');
    await flushOrgs();

    expect(el().querySelector('[data-testid="org-switcher"]')).toBeNull();
  });

  it('shows the org switcher with one option per org once loaded', async () => {
    setOrgs(of([org('a', 'ORG_ADMIN', 'alpha'), org('b', 'DEVELOPER', 'beta')]));
    render('ORG_ADMIN');
    await flushOrgs();

    const select = el().querySelector('[data-testid="org-switcher"]') as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    expect(Array.from(select!.options).map(o => o.textContent)).toEqual(['alpha', 'beta']);
  });

  it('switching the org persists the id and updates the selection', async () => {
    setOrgs(of([org('a', 'ORG_ADMIN', 'alpha'), org('b', 'DEVELOPER', 'beta')]));
    render('ORG_ADMIN');
    await flushOrgs();

    const select = el().querySelector('[data-testid="org-switcher"]') as HTMLSelectElement;
    select.value = 'b';
    select.dispatchEvent(new Event('change'));

    expect(localStorage.getItem('codesage_active_org')).toBe('b');
    expect(select.value).toBe('b');
  });

  it('renders the header even when the org list fails to load', () => {
    setOrgs(throwError(() => new Error('network down')));
    auth.currentUser.set(user('ORG_ADMIN'));

    fixture = TestBed.createComponent(SiteHeaderComponent);
    fixture.detectChanges();

    expect(el().querySelector('[data-testid="site-header"]')).not.toBeNull();
    // Role-based entries still render from the profile — orgs only drive the switcher.
    expect(linkTexts()).toContain('Organization');
    expect(el().querySelector('[data-testid="org-switcher"]')).toBeNull();
  });
});
