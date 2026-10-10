import { signal, WritableSignal } from '@angular/core';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';

import { TopbarComponent } from './topbar.component';
import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService, OrgSummary } from '../../../core/services/org-settings.service';
import { User } from '../../../core/models/user.model';

@Component({
  standalone: true,
  template: ''
})
class StubComponent {}

describe('TopbarComponent', () => {
  let fixture: ComponentFixture<TopbarComponent>;
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

  function render(): void {
    fixture = TestBed.createComponent(TopbarComponent);
    fixture.detectChanges();
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  /** ensureOrgs() resolves in a microtask — flush before DOM assertions. */
  async function flushOrgs(): Promise<void> {
    await fixture.whenStable();
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
      imports: [TopbarComponent],
      providers: [
        provideRouter([
          { path: 'dashboard', component: StubComponent },
          { path: 'repositories/:owner/:repo/pulls/:number', component: StubComponent }
        ]),
        { provide: AuthService, useValue: auth },
        { provide: OrgSettingsService, useValue: orgSvc }
      ]
    });
  });

  afterEach(() => localStorage.removeItem('codesage_active_org'));

  it('renders the header element even without a session, with no user menu', () => {
    render();

    expect(el().querySelector('[data-testid="site-header"]')).not.toBeNull();
    expect(el().querySelector('.user-menu')).toBeNull();
  });

  it('logs out and switches account through AuthService', () => {
    auth.currentUser.set(user('DEVELOPER'));
    render();

    const buttons = Array.from(el().querySelectorAll('button'));
    buttons.find(b => b.textContent?.includes('Logout'))?.click();
    buttons.find(b => b.textContent?.includes('Switch Account'))?.click();

    expect(auth.logout).toHaveBeenCalledTimes(1);
    expect(auth.switchAccount).toHaveBeenCalledTimes(1);
  });

  it('renders the avatar only when the profile carries one', () => {
    auth.currentUser.set(user('DEVELOPER'));
    render();
    expect(el().querySelector('.user-avatar')).not.toBeNull();

    auth.currentUser.set({ ...user('DEVELOPER', '') });
    fixture.detectChanges();
    expect(el().querySelector('.user-avatar')).toBeNull();
  });

  it('shows the effective role badge', () => {
    auth.currentUser.set(user('ORG_ADMIN'));
    render();

    expect(el().querySelector('[data-testid="role-badge"]')?.textContent?.trim()).toBe('ORG_ADMIN');

    auth.currentUser.set(user('NONE'));
    fixture.detectChanges();
    expect(el().querySelector('[data-testid="role-badge"]')?.textContent?.trim()).toBe('NONE');
  });

  it('hides the org switcher for a single org', async () => {
    setOrgs(of([org('only', 'ORG_ADMIN', 'single')]));
    auth.currentUser.set(user('ORG_ADMIN'));
    render();
    await flushOrgs();

    expect(el().querySelector('[data-testid="org-switcher"]')).toBeNull();
  });

  it('shows the org switcher with one option per org once loaded', async () => {
    setOrgs(of([org('a', 'ORG_ADMIN', 'alpha'), org('b', 'DEVELOPER', 'beta')]));
    auth.currentUser.set(user('ORG_ADMIN'));
    render();
    await flushOrgs();

    const select = el().querySelector('[data-testid="org-switcher"]') as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    expect(Array.from(select!.options).map(o => o.textContent)).toEqual(['alpha', 'beta']);
  });

  it('switching the org persists the id and updates the selection', async () => {
    setOrgs(of([org('a', 'ORG_ADMIN', 'alpha'), org('b', 'DEVELOPER', 'beta')]));
    auth.currentUser.set(user('ORG_ADMIN'));
    render();
    await flushOrgs();

    const select = el().querySelector('[data-testid="org-switcher"]') as HTMLSelectElement;
    select.value = 'b';
    select.dispatchEvent(new Event('change'));

    expect(localStorage.getItem('codesage_active_org')).toBe('b');
    expect(select.value).toBe('b');
  });

  it('renders the top bar even when the org list fails to load', async () => {
    setOrgs(throwError(() => new Error('network down')));
    auth.currentUser.set(user('ORG_ADMIN'));
    render();
    await flushOrgs();

    expect(el().querySelector('[data-testid="site-header"]')).not.toBeNull();
    expect(el().querySelector('[data-testid="org-switcher"]')).toBeNull();
    expect(el().querySelector('.user-menu')).not.toBeNull();
  });

  it('mirrors the drawer state onto the burger aria-expanded and emits toggles', () => {
    render();
    const burger = el().querySelector('[data-testid="nav-toggle"]') as HTMLButtonElement;

    expect(burger.getAttribute('aria-expanded')).toBe('false');
    expect(burger.getAttribute('aria-controls')).toBe('app-sidebar');

    const spy = jasmine.createSpy('toggleNav');
    fixture.componentInstance.toggleNav.subscribe(spy);
    burger.click();
    expect(spy).toHaveBeenCalledTimes(1);

    fixture.componentRef.setInput('navOpen', true);
    fixture.detectChanges();
    expect(burger.getAttribute('aria-expanded')).toBe('true');
  });

  it('builds breadcrumbs from the current route', async () => {
    render();
    expect(el().querySelector('.crumbs')).toBeNull();

    const router = TestBed.inject(Router);
    await router.navigate(['/repositories/acme/api/pulls/42']);
    fixture.detectChanges();

    const crumbs = el().querySelector('.crumbs') as HTMLElement;
    const items = Array.from(crumbs.querySelectorAll('li')).map(li => li.textContent?.trim());
    expect(items).toEqual(['Repositories/', 'acme/api/', 'Pull requests/', '#42']);

    const current = crumbs.querySelector('[aria-current="page"]');
    expect(current?.textContent?.trim()).toBe('#42');
    // Every non-final crumb is a real link.
    expect(crumbs.querySelectorAll('a').length).toBe(3);
  });
});
