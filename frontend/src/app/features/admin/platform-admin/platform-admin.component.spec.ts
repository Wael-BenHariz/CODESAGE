import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { PlatformAdminComponent } from './platform-admin.component';
import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService, OrgSummary } from '../../../core/services/org-settings.service';
import { UserService } from '../../../core/services/user.service';
import { PlatformUser, User } from '../../../core/models/user.model';

describe('PlatformAdminComponent — /users + orgs (plan Step 9)', () => {
  let fixture: ComponentFixture<PlatformAdminComponent>;
  let component: PlatformAdminComponent;
  let users: jasmine.SpyObj<UserService>;
  let orgs: jasmine.SpyObj<OrgSettingsService>;
  let role: WritableSignal<User | null>;

  const userRow = (login: string, extra: Partial<PlatformUser> = {}): PlatformUser => ({
    id: `id-${login}`,
    keycloakId: null,
    role: 'DEVELOPER',
    githubId: null,
    login,
    email: `${login}@example.com`,
    name: null,
    avatarUrl: null,
    createdAt: '2026-01-05T00:00:00Z',
    updatedAt: '2026-01-05T00:00:00Z',
    ...extra
  });

  const list = (
    items: PlatformUser[],
    page = 1,
    pages = 1,
    total = items.length
  ): { items: PlatformUser[]; page: number; pages: number; total: number; perPage: number } => ({
    items,
    page,
    pages,
    total,
    perPage: 20
  });

  const orgRow = (id: string, orgRole: string | null = null): OrgSummary => ({
    id,
    name: id,
    account_type: 'Organization',
    role: orgRole
  });

  beforeEach(() => {
    role = signal<User | null>({
      id: 'u-admin',
      login: 'platform-admin',
      email: 'pa@example.com',
      name: null,
      avatarUrl: '',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
      role: 'PLATFORM_ADMIN'
    });

    users = jasmine.createSpyObj<UserService>('UserService', ['listUsers', 'getUser']);
    orgs = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    users.listUsers.and.returnValue(of(list([userRow('octocat', { role: 'REVIEWER' })])));
    orgs.listOrgs.and.returnValue(of([orgRow('acme', 'ORG_ADMIN')]));

    TestBed.configureTestingModule({
      imports: [PlatformAdminComponent],
      providers: [
        // <app-site-header> carries routerLink directives → ActivatedRoute.
        provideRouter([]),
        provideHttpClient(),
        { provide: UserService, useValue: users },
        { provide: OrgSettingsService, useValue: orgs },
        // The header only reads currentUser()?.role for nav visibility.
        { provide: AuthService, useValue: { currentUser: role } }
      ]
    });
  });

  function create(): void {
    fixture = TestBed.createComponent(PlatformAdminComponent);
    component = fixture.componentInstance;
    fixture.detectChanges(); // ngOnInit → loadUsers + loadOrgs (sync of())
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function q(selector: string): HTMLElement | null {
    return el().querySelector(selector);
  }

  it('renders the user table read-only with the backend role vocabulary', () => {
    create();

    const table = q('[data-testid="users-table"]');
    expect(table).not.toBeNull();
    expect(table?.textContent).toContain('octocat');
    expect(table?.textContent).toContain('REVIEWER'); // passes through verbatim
    expect(q('[data-testid="users-meta"]')?.textContent).toContain('1 total');

    // Read-only: the only buttons on the screen are the pager controls —
    // no edit/suspend/role-assign affordances exist (gap §2).
    const buttons = Array.from(el().querySelectorAll('.panel button')).map(b =>
      (b.textContent ?? '').trim()
    );
    expect(buttons).toEqual(['Previous', 'Next']);
    expect(q('[data-testid="users-prev"]')?.hasAttribute('disabled')).toBeTrue();
  });

  it('paginates through GET /users page params', () => {
    users.listUsers.and.callFake((page = 1) => of(list([userRow(`user-${page}`)], page, 3, 42)));
    create();

    expect(users.listUsers).toHaveBeenCalledWith(1, 20);
    expect(q('.pager-status')?.textContent).toContain('Page 1 of 3');
    expect(q('[data-testid="users-next"]')?.hasAttribute('disabled')).toBeFalse();

    (q('[data-testid="users-next"]') as HTMLButtonElement).click();
    fixture.detectChanges(); // programmatic click doesn't auto-refresh the view

    expect(users.listUsers).toHaveBeenCalledWith(2, 20);
    expect(q('.pager-status')?.textContent).toContain('Page 2 of 3');
    expect(q('[data-testid="users-prev"]')?.hasAttribute('disabled')).toBeFalse();
  });

  it('shows the empty state when the platform has no users', () => {
    users.listUsers.and.returnValue(of(list([])));
    create();

    expect(q('[data-testid="users-empty"]')).not.toBeNull();
    expect(q('[data-testid="users-table"]')).toBeNull();
  });

  it('offers a retry when the user list fails and reloads on click', () => {
    let fail = true;
    users.listUsers.and.callFake(() =>
      fail ? throwError(() => new Error('users down')) : of(list([userRow('recovered')]))
    );
    create();

    expect(q('[data-testid="users-error"]')?.textContent).toContain('users down');

    fail = false;
    const retry = q('[data-testid="users-error"] button') as HTMLButtonElement;
    retry.click();
    fixture.detectChanges(); // programmatic click doesn't auto-refresh the view

    expect(users.listUsers).toHaveBeenCalledTimes(2);
    expect(q('[data-testid="users-table"]')?.textContent).toContain('recovered');
    expect(q('[data-testid="users-error"]')).toBeNull();
  });

  it('lists every organization with a dash when the caller holds no membership', () => {
    orgs.listOrgs.and.callFake(() => of([orgRow('acme', 'ORG_ADMIN'), orgRow('globex')]));
    create();

    const table = q('[data-testid="orgs-table"]');
    expect(table).not.toBeNull();
    expect(table?.textContent).toContain('acme');
    expect(table?.textContent).toContain('ORG_ADMIN');

    const rows = Array.from(table?.querySelectorAll('tbody tr') ?? []);
    const globexRow = rows.find(row => row.textContent?.includes('globex'));
    expect(globexRow?.textContent).toContain('—'); // role null → no membership
  });

  it('keeps an org-list failure isolated from the users panel', () => {
    orgs.listOrgs.and.callFake(() => throwError(() => new Error('orgs down')));
    create();

    expect(q('[data-testid="orgs-error"]')?.textContent).toContain('orgs down');
    expect(q('[data-testid="users-table"]')).not.toBeNull();
  });

  it('loads both panels as ready (the Platform nav entry now lives in the app-shell sidebar)', () => {
    create();

    // Shell-owned navigation: the screen no longer renders nav entries.
    expect(q('[data-testid="nav-platform"]')).toBeNull();
    expect(component.usersState()).toBe('ready');
    expect(component.orgsState()).toBe('ready');
  });

  it('shows the settings sub-nav with Platform marked current (plan Step 8)', () => {
    create();
    expect(q('[data-testid="settings-nav"]')).not.toBeNull();
    expect(q('[data-testid="settings-nav-ai"]')).not.toBeNull();
    expect(q('[data-testid="settings-nav-platform"]')?.getAttribute('aria-current')).toBe('page');
    expect(q('[data-testid="settings-nav-organization"]')?.getAttribute('aria-current')).toBeNull();
  });
});
